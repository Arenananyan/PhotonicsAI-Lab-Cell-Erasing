"""Local live preview and REST camera controls. Run with .venv/bin/python app.py."""
import argparse
import io
import json
from pathlib import Path
import socket
import threading
import time

import av
from flask import Flask, Response, jsonify, request
from blackmagic_camera import BlackmagicCamera, CameraError
from viewport import Viewport

ROOT = Path(__file__).resolve().parent


class VideoReceiver:
    def __init__(self, port=1935):
        self.port = port
        self.condition = threading.Condition()
        self.jpeg = None
        self.received_at = 0
        self.frame_count = 0
        self.error = 'Waiting for iPhone stream'
        self.started_by_app = False
        self.start_lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._receive, daemon=True).start()

    def _receive(self):
        while True:
            try:
                with av.open(f'rtmp://0.0.0.0:{self.port}/live/camera', mode='r',
                             options={'listen': '1', 'rw_timeout': '15000000',
                                      'probesize': '1000000', 'analyzeduration': '1000000'}) as container:
                    last_preview = 0
                    for frame in container.decode(video=0):
                        now = time.monotonic()
                        if now - last_preview < 0.10:
                            continue
                        last_preview = now
                        picture = frame.to_image()
                        picture.thumbnail((1280, 1280))
                        out = io.BytesIO()
                        picture.save(out, 'JPEG', quality=88)
                        with self.condition:
                            self.jpeg = out.getvalue()
                            self.received_at = time.time()
                            self.frame_count += 1
                            self.error = ''
                            self.condition.notify_all()
            except Exception as exc:
                self.error = str(exc)
                print('Video receiver:', exc, flush=True)
                time.sleep(1)

    def snapshot(self):
        with self.condition:
            if self.jpeg is None or time.time() - self.received_at > 3:
                raise CameraError('No fresh video frame. Start the stream and keep Blackmagic Camera open.')
            return self.jpeg

    def mjpeg(self, viewport=None):
        last = -1
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.frame_count != last, timeout=2)
                if self.frame_count == last or self.jpeg is None:
                    last = self.frame_count
                    continue
                last = self.frame_count
                data = self.jpeg
            if viewport is not None:
                data, _ = viewport.render(data)
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + data + b'\r\n'


def create_app(camera, receiver):
    app = Flask(__name__)
    viewport = Viewport()

    @app.get('/video/view')
    def view_video():
        return Response(receiver.mjpeg(viewport), mimetype='multipart/x-mixed-replace; boundary=frame')

    @app.get('/snapshot-view.jpg')
    def view_snapshot():
        payload, state = viewport.render(receiver.snapshot())
        return Response(payload, mimetype='image/jpeg', headers={'Cache-Control':'no-store',
            'X-View-Metadata':json.dumps(state)})

    @app.get('/api/view')
    def view_status():
        return jsonify(viewport.state())

    @app.post('/api/view')
    def view_control():
        if request.headers.get('X-Camera-Control') != 'local':
            return jsonify(error='Missing local control header'),403
        data=request.get_json(silent=True)
        if not isinstance(data,dict):
            raise ValueError('Expected a JSON object.')
        return jsonify(viewport.control(data.get('action'),data.get('value'),
                       data.get('direction'),data.get('step',.2)))

    @app.get('/')
    def index():
        return (ROOT / 'index.html').read_text()

    @app.get('/video')
    def video():
        return Response(receiver.mjpeg(), mimetype='multipart/x-mixed-replace; boundary=frame')

    @app.get('/snapshot.jpg')
    def snapshot():
        return Response(receiver.snapshot(), mimetype='image/jpeg', headers={'Cache-Control': 'no-store'})

    @app.get('/api/status')
    def status():
        return jsonify(camera=camera.status(), frames=receiver.frame_count,
                       frame_age=round(time.time()-receiver.received_at, 1) if receiver.received_at else None,
                       video_error=receiver.error)

    @app.post('/api/control')
    def control():
        if request.headers.get('X-Camera-Control') != 'local':
            return jsonify(error='Missing local control header'), 403
        data = request.get_json()
        action = data.get('action')
        operations = {'zoom': camera.set_zoom, 'focus': camera.set_focus,
                      'iso': camera.set_iso, 'white_balance': camera.set_white_balance}
        if action in operations:
            operations[action](float(data['value']))
        elif action == 'autofocus':
            camera.autofocus()
        elif action == 'start':
            with receiver.start_lock:
                if receiver.received_at and time.time() - receiver.received_at < 3:
                    return jsonify(ok=True, already_live=True)
                # Blackmagic can still report Streaming after the old receiver
                # exits. A new receiver requires a fresh outgoing connection.
                camera.stop_stream()
                deadline = time.monotonic() + 5
                while not camera.request('/livestreams/0/stop'):
                    if time.monotonic() >= deadline:
                        raise CameraError('Camera did not stop its previous stream. Try again.')
                    time.sleep(0.1)
                configure_local_stream(camera, receiver.port)
                # Let the old RTMP connection close and the receiver reopen
                # its listener before the phone creates a new connection.
                time.sleep(2)
                camera.start_stream()
                receiver.started_by_app = True
        elif action == 'stop':
            camera.stop_stream()
            receiver.started_by_app = False
        elif action == 'save':
            payload = receiver.snapshot()
            folder = ROOT / 'captures'
            folder.mkdir(exist_ok=True)
            target = folder / f'frame-{time.time_ns()}.jpg'
            target.write_bytes(payload)
            return jsonify(ok=True, saved=str(target))
        else:
            raise ValueError('Unknown action')
        return jsonify(ok=True)

    @app.errorhandler(CameraError)
    @app.errorhandler(ValueError)
    @app.errorhandler(KeyError)
    def error(exc):
        app.logger.warning('Camera request failed: %s', exc)
        return jsonify(error=str(exc)), 400

    return app


def configure_local_stream(camera, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    host = camera.base_url.split('/')[2].split(':')[0]
    try:
        sock.connect((host, 4444))
        local_ip = sock.getsockname()[0]
    finally:
        sock.close()
    if not camera.request('/livestreams/0/stop'):
        raise CameraError('A stream is already active. Stop it before reconfiguring.')
    backup = ROOT / 'previous_stream.json'
    if not backup.exists():
        backup.write_text(json.dumps(camera.request('/livestreams/0/activePlatform')))
    url = f'rtmp://{local_ip}:{port}/live'
    xml = (ROOT / 'local-stream.xml').read_text()
    import re
    xml = re.sub(r'<url>.*?</url>', f'<url>{url}</url>', xml)
    # Blackmagic caches service definitions even after replacing their XML.
    # Give each destination a distinct service identity when the Mac IP changes.
    service_name = f'Lab Scanner {local_ip.replace(".", "-")} {port}'
    xml = xml.replace('<name>Lab Scanner Local</name>', f'<name>{service_name}</name>')
    filename = f'LabScanner-{local_ip.replace(".", "-")}-{port}.xml'
    platform_name = service_name + ' RTMP'
    if platform_name not in camera.request('/livestreams/platforms'):
        camera.request(f'/livestreams/customPlatforms/{filename}', 'PUT', xml=xml)
    camera.request('/livestreams/0/activePlatform', 'PUT', {
        'platform': platform_name, 'server': 'Mac',
        'quality': 'Streaming High', 'url': url, 'key': 'camera'})
    actual_url = camera.request('/livestreams/0/activePlatform').get('url')
    if actual_url != url:
        raise CameraError(f'Camera kept destination {actual_url}; expected {url}.')
    print('iPhone stream destination:', url + '/camera', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--video-port', type=int, default=1935)
    parser.add_argument('--configure-stream', action='store_true')
    args = parser.parse_args()
    camera = BlackmagicCamera(args.host)
    if args.configure_stream:
        configure_local_stream(camera, args.video_port)
    receiver = VideoReceiver(args.video_port)
    receiver.start()
    print(f'Open http://127.0.0.1:{args.port}', flush=True)
    try:
        create_app(camera, receiver).run(host='127.0.0.1', port=args.port, threaded=True, debug=False)
    finally:
        if receiver.started_by_app:
            try:
                camera.stop_stream()
            except CameraError as exc:
                print('Could not stop phone stream on exit:', exc, flush=True)


if __name__ == '__main__':
    main()
