"""Freeze a target only after consecutive, unambiguous calibrated observations."""
from datetime import datetime, timezone
import json
import math
import time
from uuid import uuid4
from .errors import VisionError


def select_target(result, label, previous=None, selection="unique"):
    candidates = [c for c in result.detections if c.label == label
                  and c.calibration_status == 'valid' and c.printer_coordinates_mm is not None]
    if selection == 'largest':
        candidates = sorted([c for c in candidates if c.color == 'blue' and c.area_mm2 is not None],
                            key=lambda c: c.area_mm2, reverse=True)
        if not candidates or (len(candidates)>1 and candidates[0].area_mm2 <= candidates[1].area_mm2*1.05):
            return None
        winner = candidates[0]
        if previous is None:
            return winner
        if math.hypot(winner.printer_coordinates_mm.x-previous[0],
                      winner.printer_coordinates_mm.y-previous[1]) > 5:
            return None
        # Close competing candidates cannot establish identity reliably.
        if sum(math.hypot(c.printer_coordinates_mm.x-previous[0],
                         c.printer_coordinates_mm.y-previous[1])<=5 for c in candidates)!=1:
            return None
        return winner
    if previous is None:
        return candidates[0] if len(candidates) == 1 else None
    nearby = [c for c in candidates if math.hypot(
        c.printer_coordinates_mm.x-previous[0], c.printer_coordinates_mm.y-previous[1]) <= 5]
    return nearby[0] if len(nearby) == 1 else None


def stable_samples(samples, tolerance):
    points = [(c.printer_coordinates_mm.x, c.printer_coordinates_mm.y) for _, c in samples]
    return all(math.dist(a, b) <= tolerance for a in points for b in points)


def lock_target(live, directory, label='defective', stable_seconds=2.0,
                tolerance_mm=3.0, timeout_seconds=10.0, selection="unique"):
    values = (stable_seconds, tolerance_mm, timeout_seconds)
    if (selection not in ('unique', 'largest') or (selection=='largest' and label!='defective') or label not in ('healthy', 'defective') or any(isinstance(v, bool) or
        not isinstance(v, (int, float)) or not math.isfinite(v) for v in values) or
        not .5 <= stable_seconds <= 10 or not .1 <= tolerance_mm <= 5 or
        not stable_seconds < timeout_seconds <= 15):
        raise VisionError('INVALID_TARGET_OPTIONS', 'Use stable_seconds 0.5..10, tolerance_mm 0.1..5 and timeout greater than stable_seconds, at most 15.')
    samples, seen, previous, calibration_id = [], None, None, None
    started = time.monotonic()
    stable_started = None
    while time.monotonic()-started < timeout_seconds:
        try:
            result, jpeg = live.current()
        except VisionError:
            samples, previous, stable_started = [], None, None
            time.sleep(.1)
            continue
        if result.frame_id == seen:
            time.sleep(.05)
            continue
        seen = result.frame_id
        cell = select_target(result, label, previous, selection)
        if cell is None or (calibration_id is not None and cell.calibration_id != calibration_id):
            samples, previous, stable_started, calibration_id = [], None, None, None
            continue
        if not samples:
            stable_started = time.monotonic()
        samples.append((result, cell))
        previous = (cell.printer_coordinates_mm.x, cell.printer_coordinates_mm.y)
        calibration_id = cell.calibration_id
        if not stable_samples(samples, tolerance_mm):
            samples = [(result, cell)]
            stable_started = time.monotonic()
        if len(samples) >= 3 and time.monotonic()-stable_started >= stable_seconds:
            target_id = uuid4().hex
            target = dict(ok=True, status='locked', target_id=target_id,
                selection=selection,
                locked_at=datetime.now(timezone.utc).isoformat(), frame_id=result.frame_id,
                acquired_at=result.frame.acquired_at, frame_ids=[r.frame_id for r, _ in samples],
                sample_count=len(samples), stable_seconds=stable_seconds, tolerance_mm=tolerance_mm,
                calibration_id=cell.calibration_id, label=cell.label, color=cell.color,
                printer_coordinates_mm=cell.printer_coordinates_mm.model_dump(),
                pixel_center=cell.center.model_dump(), area_mm2=cell.area_mm2,
                coordinate_space='printer_mm', motion_sent=False,
                note='Frozen measurement, not movement authorization. Reacquire if the cell or grid changes.')
            directory.mkdir(parents=True, exist_ok=True)
            image = directory / (target_id+'.annotated.jpg')
            with image.open('xb') as file:
                file.write(jpeg)
            target['annotated_image'] = str(image)
            path = directory / (target_id+'.json')
            target['result_json'] = str(path)
            with path.open('x') as file:
                json.dump(target, file, indent=2)
            return target
        time.sleep(.05)
    raise VisionError('TARGET_UNSTABLE', 'No unique calibrated target stayed stable. Keep the board stationary and visible; select a label with one cell.', 409)
