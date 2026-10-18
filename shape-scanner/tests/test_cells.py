import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

import cv2
import numpy as np
from camera_vision.acquisition import CameraClient, decode_image
from camera_vision.detector import detect_cells
from camera_vision.errors import VisionError
from camera_vision.live import LiveScanner
from camera_vision.models import ScanResult
from camera_vision.service import ScanService
from camera_vision.synthetic import make_scene
from camera_vision.web import create_app


def encode(image):
    ok, payload = cv2.imencode('.png', image)
    assert ok
    return payload.tobytes()


class ColorDetectionTests(unittest.TestCase):
    def counts(self, name):
        cells = detect_cells(make_scene(name), 'test-frame')
        return {label: sum(c.label == label for c in cells) for label in ('defective', 'healthy')}

    def test_one_red_cell_and_pixel_center(self):
        cells = detect_cells(make_scene('one_red'), 'one-red')
        self.assertEqual(len(cells), 1)
        cell = cells[0]
        self.assertEqual(cell.label, 'defective')
        self.assertEqual(cell.frame_id, 'one-red')
        self.assertAlmostEqual(cell.center.x, 180, delta=1)
        self.assertAlmostEqual(cell.center.y, 160, delta=1)
        self.assertLess(cell.bbox.x, cell.center.x)
        self.assertGreater(cell.bbox.x + cell.bbox.width, cell.center.x)

    def test_multiple_red_cells(self):
        self.assertEqual(self.counts('multiple_red'), {'defective': 3, 'healthy': 0})

    def test_no_red_cells(self):
        self.assertEqual(self.counts('no_red'), {'defective': 0, 'healthy': 1})
        self.assertEqual(detect_cells(np.full((300, 400, 3), 240, np.uint8), 'empty'), [])

    def test_red_and_green_together(self):
        self.assertEqual(self.counts('mixed'), {'defective': 2, 'healthy': 2})

    def test_blue_green_real_mode_and_grid_reference(self):
        cells = detect_cells(make_scene('mixed', 'blue'), 'blue-mode', defective_color='blue')
        self.assertEqual(sum(c.color == 'blue' for c in cells), 2)
        self.assertEqual(sum(c.color == 'green' for c in cells), 2)
        with tempfile.TemporaryDirectory() as directory:
            result = ScanService(Path(directory), defective_color='blue').scan_demo()
            self.assertEqual(result.defective_color, 'blue')
            self.assertEqual(result.reference_grid.cell_side_mm, 4)
            self.assertFalse(result.reference_grid.used_for_calibration)

    def test_blue_reflections_on_dark_background_are_ignored(self):
        image = make_scene('mixed', 'blue')
        image[220:300, 450:630] = (60, 60, 60)
        cv2.circle(image, (560, 260), 20, (75, 42, 40), -1)
        cells = detect_cells(image, 'reflection', defective_color='blue')
        self.assertEqual(sum(c.color == 'blue' for c in cells), 2)

    def test_small_glare_gap_does_not_split_one_blue_cell(self):
        hsv = np.full((240, 360, 3), (0, 0, 240), np.uint8)
        cv2.rectangle(hsv, (100, 80), (180, 160), (110, 220, 180), -1)
        cv2.rectangle(hsv, (138, 80), (142, 160), (0, 0, 240), -1)
        image = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        cells = detect_cells(image, 'glare-gap', defective_color='blue')
        self.assertEqual(len(cells), 1)
        self.assertAlmostEqual(cells[0].center.x, 140, delta=1)

    def test_noise(self):
        self.assertEqual(self.counts('noise'), {'defective': 2, 'healthy': 2})

    def test_different_lighting(self):
        for factor in (.32, .55, 1.1):
            with self.subTest(brightness=factor):
                image = np.clip(make_scene('mixed').astype(float)*factor, 0, 255).astype(np.uint8)
                cells = detect_cells(image, 'lighting')
                self.assertEqual(sum(c.label == 'defective' for c in cells), 2)
                self.assertEqual(sum(c.label == 'healthy' for c in cells), 2)

    def test_red_hue_wraparound_and_blue_ignored(self):
        hsv = np.full((240, 360, 3), (0, 0, 240), np.uint8)
        cv2.circle(hsv, (80, 110), 28, (179, 220, 180), -1)
        cv2.circle(hsv, (240, 110), 28, (110, 220, 180), -1)
        cells = detect_cells(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR), 'hues')
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0].color, 'red')

    def test_outlined_and_clipped_regions(self):
        image = np.full((300, 400, 3), 240, np.uint8)
        cv2.circle(image, (120, 130), 35, (0, 0, 220), 6)
        cv2.circle(image, (0, 230), 30, (0, 170, 0), -1)
        cells = detect_cells(image, 'outline')
        self.assertEqual(len(cells), 2)
        self.assertGreater(cells[0].area_px2, 3000)
        self.assertTrue(cells[1].touches_image_edge)

    def test_invalid_images(self):
        for image in (None, np.zeros((0, 0, 3), np.uint8), np.zeros((10, 10), np.uint8),
                      np.zeros((10, 10, 3), np.float32)):
            with self.subTest(image_type=type(image)):
                with self.assertRaises(VisionError):
                    detect_cells(image, 'invalid')
        for payload in (b'', b'not an image'):
            with self.assertRaises(VisionError):
                decode_image(payload)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = ScanService(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def test_raw_and_annotated_saved_separately_and_never_overwritten(self):
        payload = encode(make_scene('mixed'))
        first = self.service.scan_payload(payload)
        files = {p.name: p.read_bytes() for p in Path(self.temp.name).iterdir()}
        second = self.service.scan_payload(payload)
        repeated = self.service.scan_frame(first.frame_id)
        self.assertNotEqual(first.frame_id, second.frame_id)
        self.assertEqual(first.frame_id, repeated.frame_id)
        self.assertNotEqual(first.annotated_image, repeated.annotated_image)
        for name, content in files.items():
            self.assertEqual((Path(self.temp.name)/name).read_bytes(), content)
        self.assertEqual(Path(first.frame.raw_image).read_bytes(), payload)
        self.assertNotEqual(first.frame.raw_image, first.annotated_image)
        self.assertEqual(ScanResult.model_validate_json(Path(first.result_json).read_bytes()), first)
        self.assertTrue(all(c.frame_id == first.frame_id for c in first.detections))
        self.assertEqual(first.coordinate_space, 'image_pixels')

    def test_capture_can_save_raw_before_analysis(self):
        frame = self.service.capture_demo()
        self.assertTrue(Path(frame.raw_image).is_file())
        self.assertEqual(len(list(Path(self.temp.name).glob('*.annotated.png'))), 0)
        result = self.service.scan_frame(frame.frame_id)
        self.assertEqual(result.frame_id, frame.frame_id)

    def test_existing_file_is_not_overwritten(self):
        self.service.store.write_new('earlier.png', b'old image')
        with self.assertRaises(VisionError):
            self.service.store.write_new('earlier.png', b'new image')
        self.assertEqual((Path(self.temp.name)/'earlier.png').read_bytes(), b'old image')

    def test_invalid_input_saves_nothing(self):
        with self.assertRaises(VisionError):
            self.service.scan_payload(b'invalid')
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_camera_unavailable(self):
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('offline')):
            with self.assertRaises(VisionError) as caught:
                self.service.scan_camera()
        self.assertEqual(caught.exception.code, 'CAMERA_UNAVAILABLE')
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_camera_rejected_control_preserves_error(self):
        error = urllib.error.HTTPError('http://localhost/api/control', 400, 'Bad Request', {},
                                        io.BytesIO(b'{"error":"ISO unsupported"}'))
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(VisionError) as caught:
                self.service.camera.control('iso', 400)
        self.assertEqual(caught.exception.code, 'CAMERA_REQUEST_FAILED')
        self.assertIn('ISO unsupported', str(caught.exception))

    def test_api_demo_without_hardware(self):
        live = LiveScanner(self.service, demo=True)
        client = create_app(self.service, live).test_client()
        with patch.object(self.service.camera, 'capture', side_effect=AssertionError('Hardware accessed')):
            response = client.post('/api/scan', json={})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['counts'], {'defective': 2, 'healthy': 2})
            self.assertEqual(response.json['frame']['source'], 'demo')
            raw = client.get('/api/frames/'+response.json['frame_id']+'/raw')
            self.assertEqual(raw.status_code, 200)
            raw.close()
            self.assertEqual(client.get('/api/camera/status').status_code, 503)

    def test_api_camera_unavailable(self):
        live = LiveScanner(self.service)
        client = create_app(self.service, live).test_client()
        with patch.object(self.service.camera, 'capture', side_effect=VisionError('CAMERA_UNAVAILABLE', 'offline', 503)):
            response = client.post('/api/scan', json={})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['error']['code'], 'CAMERA_UNAVAILABLE')

    def test_api_invalid_upload_and_request(self):
        client = create_app(self.service, LiveScanner(self.service, demo=True)).test_client()
        response = client.post('/api/scan-upload', data={'image': (io.BytesIO(b'bad'), 'bad.png')})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(client.post('/api/scan', json=[]).status_code, 400)
        self.assertEqual(client.post('/api/scan', json={'frame_id': '../secret'}).status_code, 404)

    def test_invalid_control_before_network(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('Network accessed')):
            for action, value in [('zoom', 2), ('focus', float('nan')), ('iso', -1), ('printer', None)]:
                with self.assertRaises(VisionError):
                    self.service.camera.control(action, value)

    def test_live_unavailable_clears_result(self):
        live = LiveScanner(self.service)
        with self.assertRaises(VisionError):
            live.current()


if __name__ == '__main__':
    unittest.main()
