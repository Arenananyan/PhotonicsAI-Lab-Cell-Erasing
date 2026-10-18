"""Acquire JPEG frames and proxy controls through the preserved camera app."""
import json
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import urlparse

import cv2
import numpy as np
from .errors import VisionError

MAX_BYTES = 20 * 1024 * 1024


def decode_image(payload: bytes) -> np.ndarray:
    if not payload or len(payload) > MAX_BYTES:
        raise VisionError('INVALID_IMAGE', 'Image must contain 1 byte to 20 MiB of encoded image data.')
    image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
    if image is None or min(image.shape[:2]) < 8:
        raise VisionError('INVALID_IMAGE', 'Cannot decode this file as a usable image.')
    if image.shape[0] * image.shape[1] > 30_000_000:
        raise VisionError('INVALID_IMAGE', 'Image exceeds the 30-megapixel limit.')
    return image


def read_file(path: str) -> bytes:
    try:
        with Path(path).open('rb') as handle:
            payload = handle.read(MAX_BYTES + 1)
    except OSError as exc:
        raise VisionError('INVALID_IMAGE', f'Cannot read image: {exc}') from exc
    decode_image(payload)
    return payload


class CameraClient:
    def __init__(self, preview_url: str = 'http://127.0.0.1:8765', timeout: float = 5):
        parsed = urlparse(preview_url)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise VisionError('INVALID_CAMERA_URL', 'Use the local camera preview server URL.')
        self.base_url = preview_url.rstrip('/')
        self.timeout = timeout

    def _request(self, path: str, data: dict | None = None) -> bytes:
        body = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(self.base_url + path, data=body,
            headers={'Content-Type': 'application/json', 'X-Camera-Control': 'local'})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read(MAX_BYTES+1)
        except urllib.error.HTTPError as exc:
            detail = exc.read(1000).decode(errors='replace')
            if data is not None:
                raise VisionError('CAMERA_REQUEST_FAILED', f'Camera control rejected: {detail}', 422) from exc
            raise VisionError('CAMERA_UNAVAILABLE', f'Camera preview unavailable: {detail}', 503) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise VisionError('CAMERA_UNAVAILABLE',
                f'Camera preview unavailable. Keep Blackmagic Camera open and start preview at {self.base_url}. {exc}', 503) from exc
        if len(payload) > MAX_BYTES:
            raise VisionError('CAMERA_UNAVAILABLE', 'Camera response exceeds 20 MiB.', 503)
        return payload

    def capture(self) -> bytes:
        payload = self._request('/snapshot.jpg')
        try:
            decode_image(payload)
        except VisionError as exc:
            raise VisionError('CAMERA_UNAVAILABLE', 'Camera returned an invalid image.', 503) from exc
        return payload

    def status(self) -> dict:
        try:
            return json.loads(self._request('/api/status'))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise VisionError('CAMERA_UNAVAILABLE', 'Invalid camera status response.', 503) from exc

    def view_state(self, data: dict | None = None) -> dict:
        return json.loads(self._request('/api/view',data))

    def capture_view(self) -> tuple[bytes, dict]:
        try:
            with urllib.request.urlopen(self.base_url+'/snapshot-view.jpg',timeout=self.timeout) as response:
                payload=response.read(MAX_BYTES+1)
                metadata=json.loads(response.headers['X-View-Metadata'])
            decode_image(payload)
            return payload,metadata
        except (OSError, ValueError, KeyError, VisionError) as exc:
            raise VisionError('CAMERA_UNAVAILABLE',f'Viewing image unavailable: {exc}',503) from exc

    def control(self, action: str, value: float | None = None) -> dict:
        if action not in ('start', 'stop', 'zoom', 'focus', 'autofocus', 'iso', 'white_balance'):
            raise VisionError('INVALID_CONTROL', 'Unsupported camera action.')
        if action in ('zoom', 'focus'):
            if value is None or not np.isfinite(value) or not 0 <= value <= 1:
                raise VisionError('INVALID_CONTROL', 'Zoom/focus must be between 0 and 1.')
        if action in ('iso', 'white_balance'):
            if value is None or not np.isfinite(value) or value <= 0 or not float(value).is_integer():
                raise VisionError('INVALID_CONTROL', 'Use a positive whole number.')
        data = {'action': action}
        if value is not None:
            data['value'] = value
        try:
            return json.loads(self._request('/api/control', data))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise VisionError('CAMERA_UNAVAILABLE', 'Invalid camera control response.', 503) from exc


class IPWebcamClient(CameraClient):
    """Read full-resolution snapshots from the local IP Webcam server."""
    def __init__(self, timeout: float = 5):
        super().__init__('http://127.0.0.1:8080', timeout)

    def capture(self) -> bytes:
        try:
            payload = self._request('/shot.jpg')
        except VisionError as exc:
            raise VisionError('CAMERA_UNAVAILABLE', 'IP Webcam is unavailable at http://127.0.0.1:8080. Keep its server running.', 503) from exc
        try:
            decode_image(payload)
        except VisionError as exc:
            raise VisionError('CAMERA_UNAVAILABLE', 'IP Webcam returned an invalid image.', 503) from exc
        return payload

    def status(self) -> dict:
        image = decode_image(self.capture())
        return dict(ok=True, source='ip_webcam', preview_url=self.base_url,
                    width=image.shape[1], height=image.shape[0], controls_supported=False)

    def control(self, action: str, value: float | None = None) -> dict:
        raise VisionError('UNSUPPORTED_CAMERA_CONTROL', 'Use the IP Webcam page for this camera controls.', 422)

    def view_state(self, data: dict | None = None) -> dict:
        raise VisionError('UNSUPPORTED_CAMERA_CONTROL', 'Digital iPhone view controls are unavailable for IP Webcam.', 422)

    def capture_view(self) -> tuple[bytes, dict]:
        raise VisionError('UNSUPPORTED_CAMERA_CONTROL', 'Use camera_capture_frame for the full IP Webcam image.', 422)
