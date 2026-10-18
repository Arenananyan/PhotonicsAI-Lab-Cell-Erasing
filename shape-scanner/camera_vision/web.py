from pathlib import Path
import re
from flask import Flask, Response, jsonify, request, send_file
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

from .errors import VisionError
from .live import LiveScanner
from .service import ScanService
from .synthetic import SCENES
from .targets import lock_target
from .border import find_border
from .acquisition import decode_image, read_file

ROOT = Path(__file__).resolve().parents[1]


def create_app(service: ScanService, live: LiveScanner) -> Flask:
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024

    @app.before_request
    def acquire_source_lock():
        # Long-lived streams and target observation must let the live worker run.
        if request.path not in ('/video', '/api/targets/lock', '/api/live', '/api/live.jpg'):
            service.source_lock.acquire()
            from flask import g
            g.source_locked = True

    @app.teardown_request
    def release_source_lock(exc):
        from flask import g
        if g.pop('source_locked', False):
            service.source_lock.release()

    @app.route('/api/camera/source', methods=['GET', 'POST'])
    def camera_source():
        if request.method == 'POST':
            ensure_camera()
            selected = json_body().get('source')
            changed = selected != service.camera_id
            service.select_camera(selected)
            if changed:
                with live.condition:
                    live.result, live.jpeg, live.updated = None, None, 0.0
                    live.error = VisionError('WAITING_FOR_FRAME', 'Connecting to the selected camera.', 503)
                    live.condition.notify_all()
        return jsonify(service.camera_sources())

    @app.get('/')
    def index():
        return (ROOT/'cells.html').read_text()

    @app.get('/api/live')
    def current():
        result, _ = live.current()
        return jsonify(result.model_dump())

    @app.post('/api/targets/lock')
    def freeze_target():
        data = json_body()
        return jsonify(lock_target(live, service.store.directory/'targets',
            label=data.get('label', 'defective'),
            stable_seconds=data.get('stable_seconds', 2.0),
            tolerance_mm=data.get('tolerance_mm', 3.0),
            timeout_seconds=data.get('timeout_seconds', 10.0),
            selection=data.get('selection', 'unique')))

    @app.get('/api/config')
    def config():
        return jsonify(mode='demo' if live.demo else 'camera', scene=live.scene, scenes=list(SCENES),
                       defective_color=service.defective_color, grid_cell_mm=4.0,
                       preview_url=service.camera.base_url, camera_sources=service.camera_sources())

    @app.post('/api/demo-scene')
    def scene():
        data = json_body()
        if not live.demo or data.get('scene') not in SCENES:
            raise VisionError('INVALID_SCENE', 'Use a supported scene in demo mode.')
        live.scene = data['scene']
        return jsonify(ok=True)

    @app.get('/video')
    def video():
        return Response(live.stream(), mimetype='multipart/x-mixed-replace; boundary=frame',
                        headers={'Cache-Control': 'no-store'})

    @app.get('/api/live.jpg')
    def live_image():
        result, jpeg = live.current()
        return Response(jpeg, mimetype='image/jpeg', headers={'Cache-Control': 'no-store',
                         'X-Frame-ID': result.frame_id})

    @app.post('/api/capture')
    def capture():
        frame = service.capture_demo(live.scene) if live.demo else service.capture_camera()
        return jsonify(frame.model_dump())

    @app.get('/api/calibration')
    def calibration_status():
        return jsonify(service.calibration.status())

    @app.post('/api/calibration')
    def calibrate():
        data = json_body()
        if not isinstance(data.get('frame_id'), str):
            raise VisionError('INVALID_CALIBRATION', 'Provide reference frame_id.')
        return jsonify(service.calibration.set(data['frame_id'], data.get('pixel_points'),
            tracking_mode=data.get('tracking_mode','dynamic_reference_grid')))

    @app.post('/api/calibration/border')
    def propose_border():
        data=json_body()
        if not isinstance(data.get('frame_id'),str):
            raise VisionError('INVALID_CALIBRATION','Provide a saved camera frame_id.')
        frame=service.store.get_frame(data['frame_id'])
        if frame.source!='camera':
            raise VisionError('INVALID_CALIBRATION','Border reference requires a camera frame.')
        points,info=find_border(decode_image(read_file(frame.raw_image)))
        if points is None:
            raise VisionError('BORDER_NOT_IDENTIFIED','Keep all four thick border sides visible. '+info['status'],409)
        return jsonify(frame_id=frame.frame_id,pixel_points=points.tolist(),tracking_mode='thick_border',
                       orientation_confirmation_required=True,diagnostics=info)

    @app.delete('/api/calibration')
    def clear_calibration():
        service.calibration.clear()
        return jsonify(ok=True)

    @app.post('/api/scan')
    def scan():
        data = json_body()
        frame_id = data.get('frame_id')
        if frame_id is not None:
            if not isinstance(frame_id, str):
                raise VisionError('INVALID_FRAME_ID', 'frame_id must be a string.')
            result = service.scan_frame(frame_id)
        else:
            result = service.scan_demo(live.scene) if live.demo else service.scan_camera()
        return jsonify(result.model_dump())

    @app.post('/api/scan-upload')
    def upload():
        file = request.files.get('image')
        if file is None:
            raise VisionError('INVALID_IMAGE', 'Upload an image using multipart field image.')
        return jsonify(service.scan_payload(file.read(20*1024*1024+1)).model_dump())

    @app.get('/api/frames/<frame_id>/raw')
    def raw(frame_id):
        frame = service.store.get_frame(frame_id)
        return send_file(frame.raw_image, conditional=False, max_age=0)

    @app.get('/api/frames/<frame_id>/analyses/<analysis_id>/image')
    def annotated(frame_id, analysis_id):
        service.store.get_frame(frame_id)
        if not re.fullmatch(r'[0-9a-f]{32}', analysis_id):
            raise VisionError('INVALID_ANALYSIS_ID', 'Invalid analysis identifier.', 404)
        path = service.store.directory/f'{frame_id}_{analysis_id}.annotated.png'
        if not path.is_file():
            raise VisionError('ANALYSIS_NOT_FOUND', 'No such saved analysis.', 404)
        return send_file(path, conditional=False, max_age=0)

    def ensure_camera():
        if live.demo:
            raise VisionError('CAMERA_DISABLED', 'Hardware is disabled in demo mode.', 503)

    @app.get('/api/camera/status')
    def camera_status():
        ensure_camera()
        return jsonify(service.camera.status())

    @app.route('/api/camera/view',methods=['GET','POST'])
    def view_state():
        ensure_camera()
        return jsonify(service.camera.view_state(json_body() if request.method=='POST' else None))

    @app.post('/api/camera/view/capture')
    def capture_view():
        ensure_camera()
        payload,metadata=service.camera.capture_view()
        frame=service.store.save_frame(payload,'view',service.camera_id)
        return jsonify(frame=frame.model_dump(),view=metadata)

    @app.post('/api/camera/control')
    def camera_control():
        ensure_camera()
        data = json_body()
        action, value = data.get('action'), data.get('value')
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            raise VisionError('INVALID_CONTROL', 'value must be a number.')
        return jsonify(service.camera.control(action, value))

    @app.errorhandler(VisionError)
    def vision_error(exc):
        return jsonify(exc.as_dict()), exc.status

    @app.errorhandler(BadRequest)
    def bad_request(exc):
        return jsonify(VisionError('INVALID_REQUEST', 'Expected valid JSON.', 400).as_dict()), 400

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(exc):
        return jsonify(VisionError('INVALID_IMAGE', 'Upload exceeds 20 MiB.', 413).as_dict()), 413

    return app


def json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise VisionError('INVALID_REQUEST', 'Expected a JSON object.', 400)
    return data
