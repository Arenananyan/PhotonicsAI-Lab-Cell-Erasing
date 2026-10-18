"""Camera and cell-scanner tools, connected to run_cells.py via local HTTP."""
import argparse
import json
import os
from pathlib import Path
from uuid import uuid4
import urllib.request
import urllib.error
from mcp.server import MCPServer
from mcp.server.mcpserver import Image
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel
from typing import Literal

from camera_vision.acquisition import read_file
from camera_vision.models import FrameInfo, ScanResult
from camera_vision.errors import VisionError

mcp = MCPServer('Lab Camera Vision')
BASE_URL = os.environ.get('CAMERA_VISION_URL', 'http://127.0.0.1:8767').rstrip('/')


class CameraStatus(BaseModel):
    preview: dict


class ControlResult(BaseModel):
    ok: bool


class ViewState(BaseModel):
    zoom: float
    center_x: float
    center_y: float
    crop_normalized: dict
    coordinate_space: str
    digital: bool


class ViewCapture(BaseModel):
    frame: FrameInfo
    view: dict


@mcp.tool()
def camera_get_view() -> ViewState:
    """Read digital viewing zoom, normalized full-frame center and crop bounds. Scanner remains full-frame."""
    return ViewState.model_validate_json(fetch('/api/camera/view'))


@mcp.tool()
def camera_set_view_zoom(zoom: float) -> ViewState:
    """Set digital viewing magnification 1..8. Does not change phone lens or scanner input."""
    return ViewState.model_validate_json(fetch('/api/camera/view',{'action':'zoom','value':zoom}))


@mcp.tool()
def camera_pan_view(direction: Literal['left','right','up','down'], step: float = .2) -> ViewState:
    """Move viewing window toward a direction. Step is a fraction (0..1] of the current visible width/height.

    Zoom in above 1x first. Bounds are clamped to the source image. Up decreases source Y.
    """
    return ViewState.model_validate_json(fetch('/api/camera/view',{'action':'pan','direction':direction,'step':step}))


@mcp.tool()
def camera_reset_view() -> ViewState:
    """Return digital view to full frame: 1x zoom and centered. Scanner input is unchanged."""
    return ViewState.model_validate_json(fetch('/api/camera/view',{'action':'reset'}))


@mcp.tool()
def camera_capture_view() -> ViewCapture:
    """Capture the current digital viewing image for LLM inspection and return crop-to-full-frame mapping.

    Use camera_get_frame_image(frame.frame_id) to view the saved image. Its coordinates
    are cropped-view pixels; view.crop_pixels and output dimensions map them to the full image.
    This image is marked source=view and cannot inherit printer calibration automatically.
    """
    return ViewCapture.model_validate_json(fetch('/api/camera/view/capture',{}))


class CalibrationResponse(BaseModel):
    active: bool
    calibration: dict | None = None
    printer_origin_mm: dict | None = None


@mcp.tool()
def scanner_get_calibration() -> CalibrationResponse:
    """Read the current image-to-printer board calibration and its reference points."""
    return CalibrationResponse.model_validate_json(fetch('/api/calibration'))


@mcp.tool()
def scanner_calibrate_board(frame_id: str, pixel_points: list[list[float]],
                            tracking_mode: Literal['dynamic_reference_grid','thick_border'] = 'dynamic_reference_grid') -> CalibrationResponse:
    """Calibrate the user's confirmed 200x200 mm board from a saved camera frame.

    Supply four measured image pixels in order: (0,0), (200,0), (200,200), (0,200).
    Origin is bottom-left, printer X right, Y up. Does not move the printer.
    """
    data = json.loads(fetch('/api/calibration', {'frame_id': frame_id, 'pixel_points': pixel_points, 'tracking_mode': tracking_mode}))
    status=json.loads(fetch('/api/calibration'))
    return CalibrationResponse(active=True, calibration=data, printer_origin_mm=status['printer_origin_mm'])


@mcp.tool()
def scanner_detect_board_border(frame_id: str) -> dict:
    """Propose thick-border corners without activating calibration or moving hardware.

    Confirm the actual labelled orientation before passing these points and
    tracking_mode='thick_border' to scanner_calibrate_board. A plain square
    outline alone cannot identify a 90/180 degree axis-label rotation.
    """
    return json.loads(fetch('/api/calibration/border', {'frame_id':frame_id}))


def fetch(path: str, body: dict | None = None, payload: bytes | None = None,
          content_type: str = 'application/json') -> bytes:
    data = json.dumps(body).encode() if body is not None else payload
    request = urllib.request.Request(BASE_URL+path, data=data, headers={'Content-Type': content_type})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise ToolError(exc.read().decode(errors='replace')) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ToolError(f'CAMERA_VISION_UNAVAILABLE: start run_cells.py first. {exc}') from exc


@mcp.tool()
def camera_get_sources() -> dict:
    """List the selected input and available iPhone / localhost:8080 camera sources."""
    return json.loads(fetch('/api/camera/source'))


@mcp.tool()
def camera_select_source(source: Literal['iphone', 'ip_webcam']) -> dict:
    """Switch scanner input, discarding live results. Each camera has separate board calibration.

    IP Webcam uses localhost:8080/shot.jpg and does not support iPhone control/view tools.
    No printer movement. Reacquire any target after switching.
    """
    return json.loads(fetch('/api/camera/source', {'source': source}))


@mcp.tool()
def camera_get_status() -> CameraStatus:
    """Read camera settings and stream state. Unavailable/disabled hardware raises an error."""
    return CameraStatus(preview=json.loads(fetch('/api/camera/status')))


@mcp.tool()
def camera_capture_frame() -> FrameInfo:
    """Acquire and save raw camera image independently; return its frame_id and pixel dimensions.

    In --demo mode returns a synthetic frame without accessing hardware.
    Acquired_at is the Mac acquisition time, not a sensor exposure timestamp.
    """
    return FrameInfo.model_validate_json(fetch('/api/capture', {}))


@mcp.tool()
def camera_get_frame_image(frame_id: str) -> Image:
    """View an already captured raw frame by its frame_id."""
    payload = fetch(f'/api/frames/{frame_id}/raw')
    return Image(data=payload, format='jpeg' if payload.startswith(b'\xff\xd8') else 'png')


@mcp.tool()
def camera_start_preview() -> ControlResult:
    """Start/reconnect the iPhone preview through the existing camera app. No printer control."""
    return ControlResult.model_validate_json(fetch('/api/camera/control', {'action': 'start'}))


@mcp.tool()
def camera_stop_preview() -> ControlResult:
    """Stop the iPhone outgoing preview stream."""
    return ControlResult.model_validate_json(fetch('/api/camera/control', {'action': 'stop'}))


@mcp.tool()
def camera_set_zoom(value: float) -> ControlResult:
    """Set normalized camera zoom 0..1; this is not optical magnification."""
    return ControlResult.model_validate_json(fetch('/api/camera/control', {'action': 'zoom', 'value': value}))


@mcp.tool()
def camera_set_focus(value: float) -> ControlResult:
    """Set normalized manual focus 0..1; no physical focus distance is inferred."""
    return ControlResult.model_validate_json(fetch('/api/camera/control', {'action': 'focus', 'value': value}))


@mcp.tool()
def camera_autofocus() -> ControlResult:
    """Ask the iPhone camera to autofocus."""
    return ControlResult.model_validate_json(fetch('/api/camera/control', {'action': 'autofocus'}))


@mcp.tool()
def scanner_scan_current_frame() -> ScanResult:
    """Acquire, analyze and save a frame. Configured red/blue=defective, green=healthy simulated labels.

    Returns pixel geometry, plus explicit printer_coordinates_mm and area_mm2
    when board calibration is valid; otherwise these physical fields are null,
    identifiers and separate raw/annotated output paths. In demo mode uses synthetic input.
    """
    return ScanResult.model_validate_json(fetch('/api/scan', {}))


@mcp.tool()
def scanner_scan_saved_frame(frame_id: str) -> ScanResult:
    """Analyze an earlier camera_capture_frame result, preserving its exact frame_id.

    Creates a new analysis/output without overwriting earlier experiment images.
    """
    return ScanResult.model_validate_json(fetch('/api/scan', {'frame_id': frame_id}))


@mcp.tool()
def scanner_analyze_image(image_path: str) -> ScanResult:
    """Analyze a local image without camera hardware; save raw and annotated outputs.

    image_path is a readable path on this Mac. File inputs retain pixel coordinates; camera calibration is not applied to unrelated files.
    """
    try:
        payload = read_file(image_path)
    except VisionError as exc:
        raise ToolError(json.dumps(exc.as_dict())) from exc
    boundary = 'vision-'+uuid4().hex
    data = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="input.png"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode()+payload+f'\r\n--{boundary}--\r\n'.encode()
    return ScanResult.model_validate_json(fetch('/api/scan-upload', payload=data,
        content_type='multipart/form-data; boundary='+boundary))


@mcp.tool()
def scanner_lock_target(label: Literal['defective', 'healthy'] = 'defective',
                        stable_seconds: float = 2.0, tolerance_mm: float = 3.0,
                        timeout_seconds: float = 10.0,
                        selection: Literal['unique', 'largest'] = 'unique') -> dict:
    """Freeze one unique calibrated cell after consecutive stable frames. No printer motion.

    Selection=largest chooses the largest blue cell by calibrated area; near ties fail. Unique requires exactly one cell. Returns exact latest-frame XY/area, timestamps,
    frame IDs and saved evidence. Failure raises TARGET_UNSTABLE; never uses stale coordinates.
    Reacquire after cell/grid changes. Agent may choose window and tolerance within validated limits.
    """
    return json.loads(fetch('/api/targets/lock', dict(label=label, stable_seconds=stable_seconds,
                      tolerance_mm=tolerance_mm, timeout_seconds=timeout_seconds, selection=selection)))


@mcp.tool()
def scanner_get_live_detections() -> ScanResult:
    """Read current live pixel detections without saving an experiment.

    Live frame IDs are ephemeral; use camera_capture_frame to save a reusable frame.
    Image paths are null until an experiment is explicitly saved.
    """
    return ScanResult.model_validate_json(fetch('/api/live'))


@mcp.tool()
def scanner_get_annotated_image(frame_id: str, analysis_id: str) -> Image:
    """View the saved annotated image for an exact frame and analysis pair."""
    return Image(data=fetch(f'/api/frames/{frame_id}/analyses/{analysis_id}/image'), format='png')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--http', action='store_true', help='Use loopback Streamable HTTP instead of stdio.')
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    if args.http:
        mcp.run(transport='streamable-http', host='127.0.0.1', port=args.port)
    else:
        mcp.run()
