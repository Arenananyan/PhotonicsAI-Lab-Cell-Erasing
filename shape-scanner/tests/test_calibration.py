import tempfile
from pathlib import Path
import unittest
import cv2
import numpy as np
from camera_vision.service import ScanService
from camera_vision.errors import VisionError
from camera_vision.detector import detect_cells


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = ScanService(Path(self.tmp.name))
        self.image = np.full((500,500,3),230,np.uint8)
        for x in (50,150,250,350,450):
            cv2.line(self.image,(x,50),(x,450),(40,40,40),2)
        for y in (50,150,250,350,450):
            cv2.line(self.image,(50,y),(450,y),(40,40,40),2)
        for index in range(5):
            value=str(index*50)
            cv2.putText(self.image,value,(42+index*100,473),cv2.FONT_HERSHEY_SIMPLEX,.45,(20,20,20),1)
            cv2.putText(self.image,value,(17,455-index*100),cv2.FONT_HERSHEY_SIMPLEX,.45,(20,20,20),1)
        cv2.putText(self.image,'Y',(25,35),cv2.FONT_HERSHEY_SIMPLEX,.5,(20,20,20),1)
        cv2.putText(self.image,'X',(470,440),cv2.FONT_HERSHEY_SIMPLEX,.5,(20,20,20),1)
        cv2.circle(self.image,(210,290),20,(0,170,0),-1)
        self.points = [[50,450],[450,450],[450,50],[50,50]]
        self.frame = self.service.store.save_frame(cv2.imencode('.png',self.image)[1].tobytes(),'camera')
        self.service.calibration.set(self.frame.frame_id,self.points)

    def tearDown(self):
        self.tmp.cleanup()

    def test_confirmed_printer_origin_translation(self):
        from camera_vision.calibration import board_to_printer
        for board, expected in [((0, 0), (9, 8)), ((50, 50), (59, 58)),
                                ((200, 200), (209, 208))]:
            point = board_to_printer(*board)
            self.assertEqual((point.x, point.y), expected)

    def test_known_center_and_area_in_mm(self):
        result = self.service.scan_frame(self.frame.frame_id)
        cell = result.detections[0]
        self.assertEqual(cell.calibration_status,'valid')
        self.assertAlmostEqual(cell.printer_coordinates_mm.x,89,delta=.5)
        self.assertAlmostEqual(cell.printer_coordinates_mm.y,88,delta=.5)
        # Intersection refinement uses rasterized line centers, so allow 1%
        # rendering error against the analytically known scale.
        self.assertAlmostEqual(cell.area_mm2,cell.area_px2*.25,delta=cell.area_px2*.25*.01)
        self.assertEqual(result.coordinate_space,'image_pixels')

    def test_perspective_contour_transformation(self):
        base_area=self.service.scan_frame(self.frame.frame_id).detections[0].area_mm2
        skew_points=[[100,450],[430,410],[450,60],[60,90]]
        matrix=cv2.getPerspectiveTransform(np.float32(self.points),np.float32(skew_points))
        warped=cv2.warpPerspective(self.image,matrix,(500,500),borderValue=(230,230,230))
        frame=self.service.store.save_frame(cv2.imencode('.png',warped)[1].tobytes(),'camera')
        self.service.calibration.set(frame.frame_id,skew_points)
        cell=self.service.scan_frame(frame.frame_id).detections[0]
        self.assertAlmostEqual(cell.printer_coordinates_mm.x,89,delta=1)
        self.assertAlmostEqual(cell.printer_coordinates_mm.y,88,delta=1)
        self.assertAlmostEqual(cell.area_mm2,base_area,delta=base_area*.08)

    def test_outside_board_is_not_reported_as_printer_position(self):
        image=self.image.copy()
        cv2.circle(image,(475,475),10,(0,0,220),-1)
        frame=self.service.store.save_frame(cv2.imencode('.png',image)[1].tobytes(),'camera')
        result=self.service.scan_frame(frame.frame_id)
        self.assertFalse(any(c.color=='red' for c in result.detections))

    def test_moved_camera_updates_physical_values(self):
        shifted = cv2.warpAffine(self.image,np.float32([[1,0,8],[0,1,0]]),(500,500))
        frame=self.service.store.save_frame(cv2.imencode('.png',shifted)[1].tobytes(),'camera')
        result=self.service.scan_frame(frame.frame_id)
        self.assertEqual(result.calibration['status'],'valid')
        self.assertAlmostEqual(result.detections[0].printer_coordinates_mm.x,89,delta=1)
        self.assertAlmostEqual(result.detections[0].printer_coordinates_mm.y,88,delta=1)

    def test_interior_only_grid_has_no_absolute_coordinates(self):
        cropped=self.image[160:340,160:340]
        frame=self.service.store.save_frame(cv2.imencode('.png',cropped)[1].tobytes(),'camera')
        result=self.service.scan_frame(frame.frame_id)
        self.assertNotEqual(result.calibration['status'],'valid')
        self.assertEqual(result.detections,[])

    def test_zoom_resize_keeps_board_coordinates(self):
        resized=cv2.resize(self.image,(750,750))
        frame=self.service.store.save_frame(cv2.imencode('.png',resized)[1].tobytes(),'camera')
        result=self.service.scan_frame(frame.frame_id)
        self.assertEqual(result.calibration['status'],'valid')
        self.assertAlmostEqual(result.detections[0].printer_coordinates_mm.x,89,delta=1)
        self.assertAlmostEqual(result.detections[0].printer_coordinates_mm.y,88,delta=1)

    def test_file_or_demo_cannot_inherit_camera_calibration(self):
        result=self.service.scan_payload(cv2.imencode('.png',self.image)[1].tobytes())
        self.assertEqual(result.calibration['status'],'different_source')
        self.assertIsNone(result.detections[0].area_mm2)

    def test_invalid_calibration(self):
        for points in ([[1,2]],[[50,50],[450,50],[450,450],[50,450]],[[50,50]]*4):
            with self.assertRaises(VisionError):
                self.service.calibration.set(self.frame.frame_id,points)

    def test_tracking_fallback_and_lost_board(self):
        from unittest.mock import patch
        grid=self.service.calibration.grid
        matrix,info=grid.locate(self.image)
        self.assertIsNotNone(matrix)
        shifted=cv2.warpAffine(self.image,np.float32([[1,0,3],[0,1,2]]),(500,500))
        with patch.object(grid,'_identify',return_value=(None,{'status':'grid_reference_not_identified'})):
            matrix,info=grid.locate(shifted)
            self.assertIsNotNone(matrix,info)
            self.assertEqual(info['mode'],'dynamic_tracked_grid')
            matrix,info=grid.locate(np.full_like(self.image,230))
            self.assertIsNone(matrix)

    def test_restore_and_clear(self):
        restored=ScanService(Path(self.tmp.name))
        self.assertTrue(restored.calibration.status()['active'])
        self.assertEqual(restored.calibration.status()['printer_origin_mm'], dict(x=9,y=8))
        result=restored.scan_frame(self.frame.frame_id)
        self.assertIsNotNone(result.detections[0].area_mm2)
        restored.calibration.clear()
        self.assertFalse(ScanService(Path(self.tmp.name)).calibration.status()['active'])

if __name__=='__main__':
    unittest.main()
