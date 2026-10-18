"""Detect configured red/blue defective and green healthy regions in image pixels."""
import cv2
import numpy as np
from .errors import VisionError
from .models import CellDetection, BoundingBox, Center


def validate_image(image: np.ndarray) -> None:
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or
            image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 8):
        raise VisionError('INVALID_IMAGE', 'Expected a nonempty 8-bit BGR image with 3 channels.')


def detect_cells(image: np.ndarray, frame_id: str, min_area: float = 80,
                 defective_color: str = 'red', contours_out: dict | None = None) -> list[CellDetection]:
    validate_image(image)
    if not frame_id:
        raise VisionError('INVALID_FRAME_ID', 'A frame identifier is required.')
    if defective_color not in ('red', 'blue'):
        raise VisionError('INVALID_COLOR_MODE', 'Defective color must be red or blue.')
    hsv = cv2.cvtColor(cv2.GaussianBlur(image, (3, 3), .5), cv2.COLOR_BGR2HSV)
    neutral_values = hsv[:, :, 2][hsv[:, :, 1] < 70]
    paper_min_value = max(55, float(np.percentile(neutral_values, 80)) * .60) if neutral_values.size else 55
    masks = {
        'red': cv2.inRange(hsv, (0, 85, 40), (12, 255, 255)) |
               cv2.inRange(hsv, (168, 85, 40), (179, 255, 255)),
        'green': cv2.inRange(hsv, (35, 75, 40), (88, 255, 255)),
        'blue': cv2.inRange(hsv, (90, 65, 40), (135, 255, 255)),
    }
    detections = []
    contour_by_object = {}
    height, width = image.shape[:2]
    for color in (defective_color, 'green'):
        mask = masks[color]
        # Remove isolated color noise, then bridge small glare/compression gaps
        # inside one marker stroke.  The 7 px close is deliberately local: it
        # stabilizes a fragmented mark without joining distinct cells that are
        # visibly separated on the board.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        for index, contour in enumerate(contours):
            if hierarchy is not None and hierarchy[0,index,3]>=0:
                continue  # Skip holes, but keep islands inside a colored border.
            area = float(cv2.contourArea(contour))
            if area < min_area:
                continue
            moments = cv2.moments(contour)
            if moments['m00'] <= 0:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if not .25 <= w / h <= 4:
                continue
            # Colored cell marks lie on light, mostly neutral paper. Reject
            # blue-tinted reflections on the dark printer and other hardware.
            region = np.zeros(mask.shape, np.uint8)
            cv2.drawContours(region, [contour], -1, 255, -1)
            surround = cv2.subtract(cv2.dilate(region, np.ones((15, 15), np.uint8)), region)
            selected = surround > 0
            if not np.any(selected):
                continue
            paper_fraction = np.mean((hsv[:, :, 1][selected] < 70) &
                                     (hsv[:, :, 2][selected] > paper_min_value))
            if paper_fraction < .60:
                continue
            detections.append(CellDetection(
                frame_id=frame_id, detection_id='',
                color=color, label='healthy' if color == 'green' else 'defective',
                bbox=BoundingBox(x=x, y=y, width=w, height=h),
                center=Center(x=round(moments['m10']/moments['m00'], 2),
                              y=round(moments['m01']/moments['m00'], 2)),
                area_px2=round(area, 2),
                touches_image_edge=x == 0 or y == 0 or x+w >= width or y+h >= height))
            contour_by_object[id(detections[-1])] = contour
    detections.sort(key=lambda d: (d.bbox.y, d.bbox.x, d.color))
    for index, detection in enumerate(detections, 1):
        detection.detection_id = f'{frame_id}:{index}'
        if contours_out is not None:
            contours_out[detection.detection_id] = contour_by_object[id(detection)]
    return detections


def annotate(image: np.ndarray, detections: list[CellDetection]) -> np.ndarray:
    result = image.copy()
    for i, cell in enumerate(detections, 1):
        color = {'red': (65, 65, 255), 'blue': (255, 165, 70), 'green': (70, 210, 60)}[cell.color]
        b, c = cell.bbox, cell.center
        cv2.rectangle(result, (b.x, b.y), (b.x+b.width-1, b.y+b.height-1), color, 2)
        cx, cy = round(c.x), round(c.y)
        cv2.drawMarker(result, (cx, cy), color, cv2.MARKER_CROSS, 14, 2)
        if cell.printer_coordinates_mm is not None:
            point = cell.printer_coordinates_mm
            label = f'{i}. {cell.label} XY({point.x:.1f},{point.y:.1f})mm A={cell.area_mm2:.1f}mm2'
        else:
            label = f'{i}. {cell.label} ({c.x:.1f},{c.y:.1f})px A={cell.area_px2:.0f}px2'
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, .48, 1)
        tx = max(0, min(b.x, image.shape[1]-tw-8))
        ty = max(th+8, b.y-8)
        cv2.rectangle(result, (tx, ty-th-5), (tx+tw+7, ty+4), color, -1)
        cv2.putText(result, label, (tx+3, ty), cv2.FONT_HERSHEY_SIMPLEX,
                    .48, (15, 20, 25), 1, cv2.LINE_AA)
    return result
