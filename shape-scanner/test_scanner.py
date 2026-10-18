"""Regression checks for outline classification and unavailable-camera behavior."""
import time
import unittest

import cv2
import numpy as np

from detector import detect_shapes
from app import Scanner, create_app


class ScannerTests(unittest.TestCase):
    def test_outline_shapes_with_perspective_and_blur(self):
        image = np.full((600, 800, 3), 220, np.uint8)
        cv2.polylines(image, [np.array([[80, 160], [230, 140], [170, 320]])], True, (35, 35, 35), 9)
        cv2.polylines(image, [np.array([[370, 140], [540, 180], [515, 340], [345, 295]])], True, (35, 35, 35), 9)
        image = cv2.GaussianBlur(image, (5, 5), 1)
        _, detections = detect_shapes(image)
        self.assertEqual([d['shape'] for d in detections], ['triangle', 'quadrilateral'])

    def test_blank_circle_and_open_strokes_are_not_shapes(self):
        for color in (0, 255):
            _, detections = detect_shapes(np.full((500, 700, 3), color, np.uint8))
            self.assertEqual(detections, [])
        image = np.full((500, 700, 3), 240, np.uint8)
        cv2.circle(image, (130, 150), 65, (20, 20, 20), 8)
        cv2.polylines(image, [np.array([[310, 220], [370, 100], [450, 220]])], False, (20, 20, 20), 8)
        _, detections = detect_shapes(image)
        self.assertEqual(detections, [])

    def test_missing_and_stale_frames_fail_instead_of_reporting_zero(self):
        scanner = Scanner('http://127.0.0.1:8765')
        client = create_app(scanner).test_client()
        self.assertEqual(client.get('/api/detections').status_code, 503)
        scanner.error = ''
        scanner.result = {'ok': True, 'detections': [], 'counts': {}}
        scanner.updated = time.time() - 10
        self.assertEqual(client.get('/snapshot.jpg').status_code, 503)
        self.assertFalse(client.get('/api/detections').json['ok'])


if __name__ == '__main__':
    unittest.main()
