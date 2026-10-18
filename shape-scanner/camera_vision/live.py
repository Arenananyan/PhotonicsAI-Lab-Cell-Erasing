from .dynamic_grid import draw_board
"""Read-only live analysis in memory; saving is an explicit experiment action."""
from datetime import datetime, timezone
import threading
import time
from uuid import uuid4

import cv2
from .acquisition import decode_image
from .detector import detect_cells, annotate
from .errors import VisionError
from .models import FrameInfo, ScanResult
from .service import ScanService
from .synthetic import make_scene


class LiveScanner:
    def __init__(self, service: ScanService, demo: bool = False):
        self.service = service
        self.demo = demo
        self.scene = 'mixed'
        self.condition = threading.Condition()
        self.stopped = threading.Event()
        self.result: ScanResult | None = None
        self.jpeg: bytes | None = None
        self.error: VisionError | None = VisionError('WAITING_FOR_FRAME', 'Waiting for an image.', 503)
        self.updated = 0.0

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self) -> None:
        while not self.stopped.is_set():
            started = time.monotonic()
            try:
                with self.service.source_lock:
                    image = make_scene(self.scene, self.service.defective_color) if self.demo else decode_image(self.service.camera.capture())
                    frame_id = uuid4().hex
                    frame = FrameInfo(frame_id=frame_id, acquired_at=datetime.now(timezone.utc).isoformat(),
                        source='demo' if self.demo else 'camera', camera_id=None if self.demo else self.service.camera_id, width=image.shape[1], height=image.shape[0])
                    contours = {}
                    cells = detect_cells(image, frame_id, defective_color=self.service.defective_color, contours_out=contours)
                    calibration = self.service.calibration.apply(cells, contours, image, frame.source)
                    result = ScanResult(frame_id=frame_id, analysis_id=uuid4().hex, frame=frame,
                        defective_color=self.service.defective_color,
                        counts={name: sum(c.label == name for c in cells) for name in ('defective', 'healthy')},
                        detections=cells,
                        calibration=calibration,
                        warnings=['Partially visible regions have incomplete pixel areas.']
                            if any(c.touches_image_edge for c in cells) else [])
                    result.reference_grid.used_for_calibration = calibration['status'] == 'valid'
                    if calibration.get('detections_available') is False:
                        result.warnings.append('Grid reference could not be identified; board detections and mm measurements are unavailable.')
                    ok, jpeg = cv2.imencode('.jpg', draw_board(annotate(image, cells), calibration), [cv2.IMWRITE_JPEG_QUALITY, 88])
                    if not ok:
                        raise VisionError('IMAGE_ENCODING_FAILED', 'Cannot encode preview.', 500)
                    with self.condition:
                        self.result, self.jpeg = result, jpeg.tobytes()
                        self.error, self.updated = None, time.monotonic()
                        self.condition.notify_all()
            except VisionError as exc:
                with self.condition:
                    self.error = exc
                    self.condition.notify_all()
            except Exception as exc:
                with self.condition:
                    self.error = VisionError('PROCESSING_ERROR', f'Live analysis failed: {exc}', 500)
                    self.condition.notify_all()
            self.stopped.wait(max(.05, .3-(time.monotonic()-started)))

    def current(self) -> tuple[ScanResult, bytes]:
        with self.condition:
            if self.error:
                raise self.error
            if self.result is None or self.jpeg is None or time.monotonic()-self.updated > 3:
                raise VisionError('STALE_FRAME', 'No recent camera frame.', 503)
            return self.result, self.jpeg

    def stream(self):
        previous = ''
        while not self.stopped.is_set():
            with self.condition:
                self.condition.wait_for(lambda: self.stopped.is_set() or
                    (self.result is not None and self.result.frame_id != previous), timeout=1)
                if self.result:
                    frame_id = self.result.frame_id
                else:
                    frame_id = ''
                changed = frame_id != previous
                previous = frame_id
                try:
                    _, jpeg = self.current()
                except VisionError:
                    continue
                if not changed:
                    continue
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+jpeg+b'\r\n'
