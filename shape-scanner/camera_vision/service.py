from .dynamic_grid import draw_board
from pathlib import Path
import threading
from uuid import uuid4
import cv2
from .acquisition import CameraClient, IPWebcamClient, read_file, decode_image
from .detector import detect_cells, annotate
from .errors import VisionError
from .models import FrameInfo, ScanResult
from .storage import ImageStore
from .synthetic import make_scene
from .calibration import BoardCalibration


class ScanService:
    def __init__(self, output_dir: Path, camera: CameraClient | None = None,
                 defective_color: str = 'red'):
        self.store = ImageStore(output_dir)
        self.source_lock = threading.RLock()
        self.camera_id = 'iphone'
        self.cameras = {'iphone': camera or CameraClient(), 'ip_webcam': IPWebcamClient()}
        self.camera = self.cameras[self.camera_id]
        if defective_color not in ('red', 'blue'):
            raise VisionError('INVALID_COLOR_MODE', 'Defective color must be red or blue.')
        self.defective_color = defective_color
        self.calibrations = {name: BoardCalibration(self.store, name) for name in self.cameras}
        self.calibration = self.calibrations[self.camera_id]

    def camera_sources(self) -> dict:
        return dict(selected=self.camera_id, sources=[
            dict(id=name, label='iPhone' if name=='iphone' else 'localhost:8080',
                 preview_url=client.base_url, controls_supported=name=='iphone')
            for name, client in self.cameras.items()])

    def select_camera(self, camera_id: str) -> dict:
        with self.source_lock:
            if not isinstance(camera_id, str) or camera_id not in self.cameras:
                raise VisionError('INVALID_CAMERA_SOURCE', 'Choose iphone or ip_webcam.')
            self.camera_id = camera_id
            self.camera = self.cameras[camera_id]
            self.calibration = self.calibrations[camera_id]
            return self.camera_sources()

    def capture_camera(self) -> FrameInfo:
        with self.source_lock:
            return self.store.save_frame(self.camera.capture(), 'camera', self.camera_id)

    def capture_demo(self, scene: str = 'mixed') -> FrameInfo:
        ok, encoded = cv2.imencode('.png', make_scene(scene, self.defective_color))
        if not ok:
            raise VisionError('INVALID_IMAGE', 'Cannot create test scene.')
        return self.store.save_frame(encoded.tobytes(), 'demo')

    def scan_payload(self, payload: bytes, source: str = 'upload') -> ScanResult:
        frame = self.store.save_frame(payload, source)
        return self.scan_frame(frame.frame_id)

    def scan_file(self, path: str) -> ScanResult:
        return self.scan_payload(read_file(path), 'file')

    def scan_camera(self) -> ScanResult:
        return self.scan_frame(self.capture_camera().frame_id)

    def scan_demo(self, scene: str = 'mixed') -> ScanResult:
        return self.scan_frame(self.capture_demo(scene).frame_id)

    def scan_frame(self, frame_id: str) -> ScanResult:
        frame = self.store.get_frame(frame_id)
        image = decode_image(read_file(frame.raw_image))
        contours = {}
        detections = detect_cells(image, frame_id, defective_color=self.defective_color, contours_out=contours)
        calibration_owner = self.calibrations.get(frame.camera_id or 'iphone', self.calibration)
        calibration = calibration_owner.apply(detections, contours, image, frame.source)
        result = ScanResult(frame_id=frame_id, analysis_id=uuid4().hex, frame=frame,
            defective_color=self.defective_color,
            counts={name: sum(d.label == name for d in detections) for name in ('defective', 'healthy')},
            detections=detections, annotated_image='', result_json='',
            calibration=calibration,
            warnings=['Partially visible regions have incomplete pixel areas.']
                if any(d.touches_image_edge for d in detections) else [])
        result.reference_grid.used_for_calibration = calibration['status'] == 'valid'
        if calibration.get('detections_available') is False:
            result.warnings.append('Grid reference could not be identified; board detections and mm measurements are unavailable.')
        self.store.save_analysis(result, draw_board(annotate(image, detections), calibration))
        return result
