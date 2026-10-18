import tempfile
from pathlib import Path
import unittest
import cv2
import numpy as np
from camera_vision.border import find_border, ThickBorder
from camera_vision.service import ScanService


def board_scene():
    image=np.full((600,700,3),230,np.uint8)
    for x in (100,225,350,475,600): cv2.line(image,(x,100),(x,500),(100,100,100),1)
    for y in (100,200,300,400,500): cv2.line(image,(100,y),(600,y),(100,100,100),1)
    cv2.rectangle(image,(100,100),(600,500),(35,25,40),6)
    cv2.circle(image,(350,300),16,(210,80,30),-1)
    return image


class BorderTests(unittest.TestCase):
    def test_centerline_corners(self):
        points,info=find_border(board_scene())
        self.assertIsNotNone(points,info)
        expected=np.float32([[100,500],[600,500],[600,100],[100,100]])
        self.assertLess(float(np.max(np.linalg.norm(points-expected,axis=1))),1)
        self.assertEqual(info['mode'],'thick_border')
        self.assertTrue(all(v>=.65 for v in info['side_support']))

    def test_perspective_and_moving_board(self):
        image=board_scene();points,_=find_border(image)
        ref=dict(pixel_points=points.tolist())
        target=np.float32([[70,530],[620,540],[540,110],[170,100]])
        h=cv2.getPerspectiveTransform(points,target)
        shifted=cv2.warpPerspective(image,h,(700,600),borderValue=(230,230,230))
        matrix,info=ThickBorder(image,ref).locate(shifted)
        self.assertIsNotNone(matrix,info)
        center=cv2.perspectiveTransform(cv2.perspectiveTransform(np.float32([[[350,300]]]),h),matrix)[0,0]
        self.assertLess(float(np.linalg.norm(center-[100,100])),1)

    def test_blank_missing_border_and_ambiguous_boards_fail_closed(self):
        blank=np.full((600,700,3),230,np.uint8)
        self.assertIsNone(find_border(blank)[0])
        missing=board_scene();cv2.rectangle(missing,(90,80),(610,115),(230,230,230),-1)
        self.assertIsNone(find_border(missing)[0])
        pair=np.full((600,1400,3),230,np.uint8)
        pair[:,:700]=board_scene();pair[:,700:]=board_scene()
        points,info=find_border(pair)
        self.assertIsNone(points)
        self.assertEqual(info['status'],'border_ambiguous')

    def test_partial_image_and_invalid_input(self):
        points,_=find_border(board_scene()[:,:500])
        self.assertIsNone(points)
        with self.assertRaises(ValueError): find_border(None)

    def test_saved_border_mode_and_measurements(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=ScanService(Path(tmp),defective_color='blue')
            image=board_scene();points,_=find_border(image)
            frame=service.store.save_frame(cv2.imencode('.png',image)[1].tobytes(),'camera')
            service.calibration.set(frame.frame_id,points.tolist(),tracking_mode='thick_border')
            result=service.scan_frame(frame.frame_id)
            self.assertEqual(result.calibration['mode'],'thick_border')
            cell=next(c for c in result.detections if c.color=='blue')
            self.assertAlmostEqual(cell.printer_coordinates_mm.x,109,delta=1)
            self.assertAlmostEqual(cell.printer_coordinates_mm.y,108,delta=1)
            restored=ScanService(Path(tmp),defective_color='blue')
            self.assertEqual(restored.calibration.active['tracking_mode'],'thick_border')
            self.assertEqual(restored.scan_frame(frame.frame_id).calibration['status'],'valid')
            blank=service.store.save_frame(cv2.imencode('.png',np.full_like(image,230))[1].tobytes(),'camera')
            lost=restored.scan_frame(blank.frame_id)
            self.assertFalse(lost.calibration['measurements_available'])
            self.assertEqual(lost.detections,[])

    def test_blue_outline_is_reference_not_a_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=ScanService(Path(tmp),defective_color='blue')
            image=board_scene();cv2.rectangle(image,(100,100),(600,500),(120,40,40),6)
            points,info=find_border(image)
            self.assertIsNotNone(points,info)
            frame=service.store.save_frame(cv2.imencode('.png',image)[1].tobytes(),'camera')
            service.calibration.set(frame.frame_id,points.tolist(),tracking_mode='thick_border')
            cells=service.scan_frame(frame.frame_id).detections
            self.assertEqual(len(cells),1)
            self.assertLess(cells[0].area_mm2,200)

    def test_http_proposal_requires_explicit_application(self):
        from camera_vision.web import create_app
        from camera_vision.live import LiveScanner
        with tempfile.TemporaryDirectory() as tmp:
            service=ScanService(Path(tmp))
            image=board_scene();frame=service.store.save_frame(cv2.imencode('.png',image)[1].tobytes(),'camera')
            client=create_app(service,LiveScanner(service,demo=True)).test_client()
            proposal=client.post('/api/calibration/border',json={'frame_id':frame.frame_id})
            self.assertEqual(proposal.status_code,200)
            data=proposal.get_json()
            self.assertTrue(data['orientation_confirmation_required'])
            self.assertIsNone(service.calibration.active)
            applied=client.post('/api/calibration',json={'frame_id':frame.frame_id,
                'pixel_points':data['pixel_points'],'tracking_mode':'thick_border'})
            self.assertEqual(applied.status_code,200)
            self.assertEqual(service.calibration.active['tracking_mode'],'thick_border')
            self.assertEqual(client.get('/api/calibration').get_json()['printer_origin_mm'],dict(x=9,y=8))

    def test_short_reflection_gap_uses_line_fragments(self):
        image=board_scene()
        cv2.rectangle(image,(92,255),(108,280),(230,230,230),-1)
        points,info=find_border(image)
        self.assertIsNotNone(points,info)
        self.assertLess(float(np.max(np.linalg.norm(points-np.float32([[100,500],[600,500],[600,100],[100,100]]),axis=1))),2)

    def test_two_nested_equal_width_frames_remain_ambiguous(self):
        image=board_scene()
        cv2.rectangle(image,(180,180),(520,420),(35,25,40),6)
        points,info=find_border(image)
        self.assertIsNone(points)
        self.assertEqual(info['status'],'border_ambiguous')


class ReferenceGeometryTests(unittest.TestCase):
    def test_spurious_skinny_rectangle_is_rejected_with_reference(self):
        image=board_scene()
        reference=np.float32([[100,500],[600,500],[600,100],[100,100]])
        # Hardware/grid fragments form a thin rectangle beyond the board edge.
        cv2.rectangle(image,(275,100),(400,555),(35,25,40),6)
        matrix,info=ThickBorder(image,dict(pixel_points=reference)).locate(image)
        self.assertIsNotNone(matrix,info)
        np.testing.assert_allclose(info['board_polygon_px'],reference,atol=2)

    def test_no_old_corners_when_current_board_is_missing(self):
        image=board_scene();reference,_=find_border(image)
        tracker=ThickBorder(image,dict(pixel_points=reference))
        matrix,info=tracker.locate(np.full_like(image,230))
        self.assertIsNone(matrix)
        self.assertNotEqual(info['status'],'valid')

    def test_two_same_size_boards_remain_ambiguous_with_reference(self):
        image=np.full((600,1400,3),230,np.uint8)
        image[:,:700]=board_scene();image[:,700:]=board_scene()
        reference=np.float32([[100,500],[600,500],[600,100],[100,100]])
        matrix,info=ThickBorder(image,dict(pixel_points=reference)).locate(image)
        self.assertIsNone(matrix)
        self.assertEqual(info['status'],'border_ambiguous')

    def test_large_camera_scale_change_requires_new_reference(self):
        reference=np.float32([[100,500],[600,500],[600,100],[100,100]])
        image=np.full((600,700,3),230,np.uint8)
        cv2.rectangle(image,(225,200),(475,400),(35,25,40),6)
        matrix,info=ThickBorder(image,dict(pixel_points=reference)).locate(image)
        self.assertIsNone(matrix)
        self.assertNotEqual(info['status'],'valid')
