"""Camera selection, acquisition errors and independent physical references."""
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import cv2
import numpy as np
from camera_vision.acquisition import CameraClient, IPWebcamClient
from camera_vision.errors import VisionError
from camera_vision.live import LiveScanner
from camera_vision.service import ScanService
from camera_vision.synthetic import make_scene
from camera_vision.web import create_app


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.payload = cv2.imencode('.jpg', make_scene('mixed', 'blue'))[1].tobytes()
        self.service = ScanService(Path(self.tmp.name), defective_color='blue')
        self.live = LiveScanner(self.service)
        self.client = create_app(self.service, self.live).test_client()

    def tearDown(self):
        self.live.stopped.set()
        if hasattr(self.live, 'thread'):
            self.live.thread.join(timeout=3)
        self.tmp.cleanup()

    def test_verified_snapshot_endpoint_and_full_dimensions(self):
        urls = []
        def request(req, timeout):
            urls.append(req.full_url)
            return BytesIO(self.payload)
        with patch('urllib.request.urlopen', side_effect=request):
            self.service.select_camera('ip_webcam')
            frame = self.service.capture_camera()
            self.assertEqual(frame.camera_id, 'ip_webcam')
            self.assertEqual(urls, ['http://127.0.0.1:8080/shot.jpg'])
            self.assertEqual(frame.width, 640)
            self.assertEqual(self.service.store.get_frame(frame.frame_id).camera_id, 'ip_webcam')
        self.assertEqual(self.service.camera.base_url, 'http://127.0.0.1:8080')

    def test_unavailable_and_invalid_camera_image(self):
        for failure in (urllib.error.URLError('offline'), None):
            with patch('urllib.request.urlopen', side_effect=failure,
                       return_value=BytesIO(b'not an image')):
                with self.assertRaises(VisionError) as caught:
                    IPWebcamClient().capture()
                self.assertEqual(caught.exception.code, 'CAMERA_UNAVAILABLE')

    def test_unsupported_controls_do_not_send_phone_requests(self):
        camera = IPWebcamClient()
        with patch('urllib.request.urlopen') as request:
            for call in (lambda: camera.control('start'), camera.view_state, camera.capture_view):
                with self.assertRaises(VisionError) as caught:
                    call()
                self.assertEqual(caught.exception.code, 'UNSUPPORTED_CAMERA_CONTROL')
            request.assert_not_called()

    def test_api_selection_validation_and_demo_isolation(self):
        self.assertEqual(self.client.get('/api/camera/source').json['selected'], 'iphone')
        response = self.client.post('/api/camera/source', json={'source':'ip_webcam'})
        self.assertEqual(response.json['selected'], 'ip_webcam')
        self.assertFalse(response.json['sources'][1]['controls_supported'])
        for source in ('unknown', ['iphone'], None):
            self.assertEqual(self.client.post('/api/camera/source', json={'source':source}).status_code, 422)
        self.assertEqual(self.service.camera_id, 'ip_webcam')
        self.live.demo = True
        self.assertEqual(self.client.post('/api/camera/source', json={'source':'iphone'}).status_code, 503)

    def test_separate_references_survive_switch_and_restart(self):
        image = np.full((500,500,3), 240, np.uint8)
        for x in range(50,451,100):
            cv2.line(image,(x,50),(x,450),(30,30,30),3)
            cv2.line(image,(50,x),(450,x),(30,30,30),3)
        payload = cv2.imencode('.png',image)[1].tobytes()
        points = [[50,450],[450,450],[450,50],[50,50]]
        phone = self.service.store.save_frame(payload,'camera','iphone')
        phone_cal = self.service.calibration.set(phone.frame_id, points)
        self.service.select_camera('ip_webcam')
        self.assertFalse(self.service.calibration.status()['active'])
        with self.assertRaises(VisionError):
            self.service.calibration.set(phone.frame_id, points)
        webcam = self.service.store.save_frame(payload,'camera','ip_webcam')
        webcam_cal = self.service.calibration.set(webcam.frame_id, points)
        self.assertNotEqual(phone_cal['calibration_id'], webcam_cal['calibration_id'])
        # Saved frames always retain their own camera reference, even after switching.
        self.assertEqual(self.service.scan_frame(phone.frame_id).calibration['calibration_id'], phone_cal['calibration_id'])
        self.service.select_camera('iphone')
        self.assertEqual(self.service.calibration.active['calibration_id'],phone_cal['calibration_id'])
        restored = ScanService(Path(self.tmp.name))
        restored.select_camera('ip_webcam')
        self.assertEqual(restored.calibration.active['calibration_id'],webcam_cal['calibration_id'])

    def test_switch_waits_for_capture_and_discards_old_live_result(self):
        entered, release = threading.Event(), threading.Event()
        def capture():
            entered.set()
            release.wait(timeout=3)
            return self.payload
        self.service.camera.capture = capture
        self.service.cameras['ip_webcam'].capture = lambda: self.payload
        self.live.start()
        self.assertTrue(entered.wait(timeout=2))
        responses = []
        def switch():
            with create_app(self.service,self.live).test_client() as client:
                responses.append(client.post('/api/camera/source',json={'source':'ip_webcam'}).status_code)
        thread = threading.Thread(target=switch)
        thread.start()
        release.set()
        thread.join(timeout=3)
        self.assertEqual(responses, [200])
        # After the switch has returned, an old phone frame must never be readable.
        deadline = time.monotonic()+3
        while time.monotonic()<deadline:
            try:
                result,_ = self.live.current()
                self.assertEqual(result.frame.camera_id,'ip_webcam')
                break
            except VisionError:
                time.sleep(.03)
        else:
            self.fail('No new-source live frame')


if __name__=='__main__':
    unittest.main()


class LiveReadConcurrency(unittest.TestCase):
    def test_live_reads_do_not_wait_for_next_frame_processing(self):
        with tempfile.TemporaryDirectory() as directory:
            service=ScanService(Path(directory))
            live=LiveScanner(service,demo=True)
            live.result=service.scan_demo()
            live.jpeg=cv2.imencode('.jpg',make_scene('mixed'))[1].tobytes()
            live.error=None;live.updated=time.monotonic()
            held,release,responded=threading.Event(),threading.Event(),threading.Event()
            def process():
                with service.source_lock:
                    held.set();release.wait(timeout=3)
            worker=threading.Thread(target=process);worker.start()
            self.assertTrue(held.wait(timeout=1))
            responses=[]
            def read():
                client=create_app(service,live).test_client()
                responses.append(client.get('/api/live').status_code)
                responded.set()
            reader=threading.Thread(target=read);reader.start()
            try:
                self.assertTrue(responded.wait(timeout=1),'Live response blocked on next-frame processing')
                self.assertEqual(responses,[200])
            finally:
                release.set();worker.join(timeout=2);reader.join(timeout=2)
