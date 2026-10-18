"""Separate shape scanner, reading the existing camera preview server."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error

import cv2
import numpy as np
from flask import Flask, Response, jsonify
from detector import detect_shapes

ROOT = Path(__file__).resolve().parent


class Scanner:
    def __init__(self, source):
        self.source = source.rstrip('/') + '/snapshot.jpg'
        self.condition = threading.Condition()
        self.stop = threading.Event()
        self.jpeg = None
        self.result = None
        self.updated = 0
        self.sequence = 0
        self.error = 'Waiting for camera'

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                with urllib.request.urlopen(self.source, timeout=3) as response:
                    payload = response.read()
                image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError('Camera returned an invalid image')
                annotated, detections = detect_shapes(image)
                ok, encoded = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 88])
                if not ok:
                    raise ValueError('Could not encode preview')
                with self.condition:
                    self.updated = time.time()
                    self.sequence += 1
                    self.jpeg = encoded.tobytes()
                    self.result = {
                        'ok': True,
                        'observed_at': datetime.fromtimestamp(self.updated, timezone.utc).isoformat(),
                        'frame': self.sequence,
                        'counts': {name: sum(d['shape'] == name for d in detections)
                                   for name in ('triangle', 'quadrilateral')},
                        'detections': detections,
                        'method': 'closed dark outlines on light paper',
                    }
                    self.error = ''
                    self.condition.notify_all()
            except Exception as exc:
                if isinstance(exc, urllib.error.HTTPError):
                    detail = exc.read().decode(errors='replace')[:300]
                    message = f'Camera has no usable frame: {detail}'
                else:
                    message = f'Camera connection: {exc}'
                with self.condition:
                    self.error = message
                    self.condition.notify_all()
            self.stop.wait(max(.05, .2 - (time.monotonic()-started)))

    def current(self):
        with self.condition:
            if self.error or not self.result or time.time() - self.updated > 2:
                return {'ok': False, 'error': self.error or 'Camera frame is stale',
                        'counts': None, 'detections': []}, None
            return dict(self.result, age_seconds=round(time.time()-self.updated, 2)), self.jpeg

    def stream(self):
        previous = -1
        while not self.stop.is_set():
            with self.condition:
                self.condition.wait_for(lambda: self.sequence != previous or self.stop.is_set(), timeout=1)
                result, jpeg = self.current()
                changed = self.sequence != previous
                previous = self.sequence
                if not changed or not result['ok']:
                    continue
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n'


def create_app(scanner):
    app = Flask(__name__)

    @app.get('/')
    def index():
        return (ROOT / 'index.html').read_text()

    @app.get('/api/detections')
    def detections():
        result, _ = scanner.current()
        return jsonify(result), 200 if result['ok'] else 503

    @app.get('/snapshot.jpg')
    def snapshot():
        result, jpeg = scanner.current()
        if not result['ok']:
            return jsonify(result), 503
        return Response(jpeg, mimetype='image/jpeg', headers={'Cache-Control': 'no-store'})

    @app.get('/video')
    def video():
        return Response(scanner.stream(), mimetype='multipart/x-mixed-replace; boundary=frame',
                        headers={'Cache-Control': 'no-store'})
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default='http://127.0.0.1:8765')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    scanner = Scanner(args.source)
    scanner.start()
    print(f'Shape scanner: http://127.0.0.1:{args.port}', flush=True)
    try:
        create_app(scanner).run(host='127.0.0.1', port=args.port, threaded=True)
    finally:
        scanner.stop.set()
        with scanner.condition:
            scanner.condition.notify_all()


if __name__ == '__main__':
    main()
