"""Planar image-to-board calibration from measured control points, no motor control."""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from uuid import uuid4

import cv2
import numpy as np
from .acquisition import read_file, decode_image
from .errors import VisionError
from .models import CellDetection, Center
from .dynamic_grid import DynamicGrid
from .border import ThickBorder, find_border


# Operator-confirmed translation; axes retain the board's positive directions.
PRINTER_ORIGIN_MM = (9.0, 8.0)


def board_to_printer(x: float, y: float) -> Center:
    return Center(x=round(x + PRINTER_ORIGIN_MM[0], 2),
                  y=round(y + PRINTER_ORIGIN_MM[1], 2))


class BoardCalibration:
    def __init__(self, store, camera_id: str = 'iphone'):
        self.camera_id = camera_id
        self.store = store
        self.directory = store.directory/'calibration'
        if camera_id != 'iphone':
            self.directory = self.directory/camera_id
        self.lock = threading.RLock()
        self.active = None
        self.matrix = None
        self.grid = None
        pointer = self.directory/'active.json'
        if pointer.is_file():
            try:
                data = json.loads(pointer.read_text())
                if data:
                    self._activate(data)
            except (OSError, ValueError, VisionError, KeyError):
                pass

    def _activate(self, data):
        frame = self.store.get_frame(data['reference_frame_id'])
        image = decode_image(read_file(frame.raw_image))
        self.matrix = np.array(data['homography'], dtype=np.float64)
        self.active = data
        self.grid = ThickBorder(image,data) if data.get('tracking_mode')=='thick_border' else DynamicGrid(image,data)

    def set(self, frame_id: str, pixel_points: list, tracking_mode: str = 'dynamic_reference_grid') -> dict:
        if tracking_mode not in ('dynamic_reference_grid','thick_border'):
            raise VisionError('INVALID_CALIBRATION', 'Unknown board tracking mode.')
        frame = self.store.get_frame(frame_id)
        if frame.source != 'camera' or (frame.camera_id or 'iphone') != self.camera_id:
            raise VisionError('INVALID_CALIBRATION', 'Use a captured camera frame for board calibration.')
        try:
            points = np.asarray(pixel_points, dtype=np.float32)
        except (TypeError, ValueError) as exc:
            raise VisionError('INVALID_CALIBRATION', 'Provide four [x,y] pixel points.') from exc
        if points.shape != (4, 2) or not np.isfinite(points).all():
            raise VisionError('INVALID_CALIBRATION', 'Provide four finite [x,y] pixel points.')
        if not cv2.isContourConvex(points.reshape(-1,1,2)) or abs(cv2.contourArea(points)) < 1000:
            raise VisionError('INVALID_CALIBRATION', 'The four corners must form a convex board.')
        if cv2.contourArea(points, oriented=True) >= 0:
            raise VisionError('INVALID_CALIBRATION', 'Click bottom-left, bottom-right, top-right, top-left in that order.')
        if ((points[:,0] < 24).any() or (points[:,0] >= frame.width-24).any() or
            (points[:,1] < 24).any() or (points[:,1] >= frame.height-24).any()):
            raise VisionError('INVALID_CALIBRATION', 'Keep each board corner at least 24 pixels inside the image.')
        if tracking_mode=='thick_border':
            image=decode_image(read_file(frame.raw_image))
            detected,info=find_border(image)
            if detected is None or np.max(np.linalg.norm(detected-points,axis=1))>20:
                raise VisionError('INVALID_CALIBRATION', 'Confirm the four detected thick-border corners in bottom-left-first order.')
            points=detected
        board = np.float32([[0,0],[200,0],[200,200],[0,200]])
        matrix = cv2.getPerspectiveTransform(points, board)
        data = dict(calibration_id=uuid4().hex, reference_frame_id=frame_id, camera_id=self.camera_id,
            tracking_mode=tracking_mode, created_at=datetime.now(timezone.utc).isoformat(), width=frame.width, height=frame.height,
            pixel_points=points.tolist(), board_points_mm=board.tolist(),
            board_width_mm=200.0, board_height_mm=200.0, small_grid_cell_mm=4.0,
            large_grid_cell_mm=50.0, homography=matrix.tolist(),
            origin='board_bottom_left', x_direction='right', y_direction='up')
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory/(data['calibration_id']+'.json')).open('x') as file:
                json.dump(data,file,indent=2)
            self._activate(data)
            temporary = self.directory/(uuid4().hex+'.tmp')
            temporary.write_text(json.dumps(data,indent=2))
            temporary.replace(self.directory/'active.json')
        return data

    def clear(self):
        with self.lock:
            self.active, self.matrix = None, None
            self.grid = None
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory/'active.json').write_text('null')

    def status(self) -> dict:
        with self.lock:
            return {'active': self.active is not None, 'calibration': self.active,
                    'printer_origin_mm': dict(x=PRINTER_ORIGIN_MM[0], y=PRINTER_ORIGIN_MM[1])}

    def validate_frame(self, image, source: str) -> str:
        if self.active is None:
            return 'not_calibrated'
        if source != 'camera':
            return 'different_source'
        return self.grid.locate(image)[1]['status']

    def apply(self, cells: list[CellDetection], contours: dict, image, source: str) -> dict:
        with self.lock:
            if self.active is None:
                matrix,info=None,{'status':'not_calibrated'}
            elif source!='camera':
                matrix,info=None,{'status':'different_source'}
            else:
                matrix,info=self.grid.locate(image)
            info['printer_origin_mm']=dict(x=PRINTER_ORIGIN_MM[0], y=PRINTER_ORIGIN_MM[1])
            state=info['status']
            info['measurements_available']=state=='valid'
            info['detection_scope']='board_only' if source=='camera' and self.active else 'full_image'
            info['detections_available']=not (source=='camera' and self.active and state!='valid')
            info['calibration_id']=self.active['calibration_id'] if self.active else None
            if source=='camera' and self.active is not None and state!='valid':
                cells.clear()
                return info
            retained=[]
            for cell in cells:
                cell.calibration_status = state
                if state != 'valid':
                    retained.append(cell)
                    continue
                point=cv2.perspectiveTransform(np.float32([[[cell.center.x,cell.center.y]]]),matrix)[0,0]
                if not (0<=point[0]<=200 and 0<=point[1]<=200):
                    continue
                if cell.touches_image_edge:
                    cell.calibration_status = 'partial_region'
                    retained.append(cell)
                    continue
                contour = contours[cell.detection_id].astype(np.float32)
                transformed = cv2.perspectiveTransform(contour, matrix)
                if info.get('mode')=='thick_border':
                    xy=transformed.reshape(-1,2)
                    edge_distance=np.min(np.abs(np.stack((xy[:,0],xy[:,1],200-xy[:,0],200-xy[:,1]))),axis=0)
                    if np.ptp(xy[:,0])>180 and np.ptp(xy[:,1])>180 and np.mean(edge_distance<3)>.7:
                        continue  # The outline itself is a reference, never a cell.
                retained.append(cell)
                if (transformed < -.5).any() or (transformed > 200.5).any():
                    cell.calibration_status = 'outside_board'
                    continue
                moments = cv2.moments(transformed)
                if moments['m00'] <= 0:
                    continue
                cell.printer_coordinates_mm = board_to_printer(
                    moments['m10']/moments['m00'],
                    moments['m01']/moments['m00'])
                cell.area_mm2 = round(abs(cv2.contourArea(transformed)),2)
                cell.calibration_id = info['calibration_id']
            cells[:]=retained
            return info
