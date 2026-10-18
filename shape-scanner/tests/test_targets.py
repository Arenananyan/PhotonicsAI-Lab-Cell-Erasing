import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from camera_vision.targets import lock_target, select_target, stable_samples
from camera_vision.errors import VisionError


def cell(x=60):
    from camera_vision.models import CellDetection
    return CellDetection(frame_id='a',detection_id='a:1', label='defective',color='blue',
        bbox=dict(x=1,y=1,width=10,height=10), center=dict(x=6,y=6), area_px2=100,
        touches_image_edge=False,printer_coordinates_mm=dict(x=x,y=30),area_mm2=25,
        calibration_status='valid',calibration_id='cal')


class Targets(unittest.TestCase):
    def test_ambiguous_or_invalid_cell_rejected(self):
        c=cell()
        self.assertIsNone(select_target(NS(detections=[c,c]),'defective'))
        c.calibration_status='partial_region'
        self.assertIsNone(select_target(NS(detections=[c]),'defective'))

    def test_jitter_rejected(self):
        self.assertFalse(stable_samples([(None,cell(60)),(None,cell(62))],1))

    def test_saved_target_and_fresh_frames(self):
        class Live:
            count=0
            def current(self):
                self.count+=1
                return NS(frame_id=str(self.count),detections=[cell()],
                          frame=NS(acquired_at='time')),b'jpeg'
        with tempfile.TemporaryDirectory() as tmp:
            r=lock_target(Live(),Path(tmp),'defective',.5,1,1)
            self.assertFalse(r['motion_sent'])
            self.assertEqual(r['printer_coordinates_mm'],dict(x=60,y=30))
            self.assertTrue(Path(r['result_json']).is_file())
            self.assertGreaterEqual(r['sample_count'],3)

    def test_unavailable_and_invalid_options(self):
        class Offline:
            def current(self): raise VisionError('CAMERA_UNAVAILABLE','offline',503)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(VisionError) as c:
                lock_target(Offline(),Path(tmp),stable_seconds=.5,timeout_seconds=.6)
            self.assertEqual(c.exception.code,'TARGET_UNSTABLE')
            with self.assertRaises(VisionError):
                lock_target(Offline(),Path(tmp),tolerance_mm=float('nan'))

class LargestTargetTests(unittest.TestCase):
    def test_largest_blue_not_green(self):
        small,big,green=cell(40),cell(90),cell(130)
        small.area_mm2=10;big.area_mm2=30;green.area_mm2=100
        green.color='green';green.label='healthy'
        result=NS(detections=[small,big,green])
        self.assertIs(select_target(result,'defective',selection='largest'),big)

    def test_near_tie_or_largest_changed_is_rejected(self):
        a,b=cell(40),cell(90)
        a.area_mm2=30;b.area_mm2=29
        self.assertIsNone(select_target(NS(detections=[a,b]),'defective',selection='largest'))
        b.area_mm2=50
        self.assertIsNone(select_target(NS(detections=[a,b]),'defective',(40,30),'largest'))
