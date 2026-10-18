"""Append-only frame/output storage. Never overwrite an earlier experiment."""
from datetime import datetime, timezone
from pathlib import Path
import json
import re
from uuid import uuid4

import cv2
import numpy as np
from .acquisition import decode_image
from .errors import VisionError
from .models import FrameInfo, ScanResult


class ImageStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)

    def write_new(self, name: str, payload: bytes) -> Path:
        path = self.directory / name
        try:
            with path.open('xb') as file:
                file.write(payload)
        except OSError as exc:
            raise VisionError('STORAGE_ERROR', f'Could not create experiment output: {exc}', 500) from exc
        return path

    def save_frame(self, payload: bytes, source: str, camera_id: str | None = None) -> FrameInfo:
        image = decode_image(payload)
        frame_id = uuid4().hex
        suffix = '.jpg' if payload.startswith(b'\xff\xd8') else '.png'
        # Preserve JPEG/PNG bytes. Normalize other decoded formats into PNG.
        if not payload.startswith((b'\xff\xd8', b'\x89PNG')):
            ok, encoded = cv2.imencode('.png', image)
            if not ok:
                raise VisionError('STORAGE_ERROR', 'Cannot encode raw image.', 500)
            payload = encoded.tobytes()
        raw = self.write_new(f'{frame_id}.raw{suffix}', payload)
        frame = FrameInfo(frame_id=frame_id, acquired_at=datetime.now(timezone.utc).isoformat(),
            source=source, camera_id=camera_id, width=image.shape[1], height=image.shape[0], raw_image=str(raw))
        self.write_new(f'{frame_id}.frame.json', frame.model_dump_json(indent=2).encode())
        return frame

    def get_frame(self, frame_id: str) -> FrameInfo:
        if not re.fullmatch(r'[0-9a-f]{32}', frame_id):
            raise VisionError('INVALID_FRAME_ID', 'Expected a 32-character frame identifier.', 404)
        try:
            data = (self.directory/f'{frame_id}.frame.json').read_bytes()
            return FrameInfo.model_validate_json(data)
        except (OSError, ValueError) as exc:
            raise VisionError('FRAME_NOT_FOUND', f'No saved frame {frame_id}.', 404) from exc

    def save_analysis(self, result: ScanResult, image: np.ndarray) -> None:
        ok, encoded = cv2.imencode('.png', image)
        if not ok:
            raise VisionError('STORAGE_ERROR', 'Cannot encode annotated image.', 500)
        stem = f'{result.frame_id}_{result.analysis_id}'
        result.annotated_image = str(self.write_new(stem+'.annotated.png', encoded.tobytes()))
        result.result_json = str(self.directory/(stem+'.result.json'))
        self.write_new(stem+'.result.json', result.model_dump_json(indent=2).encode())
