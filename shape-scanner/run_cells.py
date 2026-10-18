"""Run a separate colored-cell scanner without changing the original shape app."""
import argparse
from pathlib import Path
from camera_vision.acquisition import CameraClient
from camera_vision.live import LiveScanner
from camera_vision.service import ScanService
from camera_vision.web import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', help='Use synthetic images, no hardware access.')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--camera-source', choices=('iphone', 'ip_webcam'), default='iphone')
    parser.add_argument('--camera-preview', default='http://127.0.0.1:8765')
    parser.add_argument('--defective-color', choices=('red', 'blue'),
                        help='Default: blue for actual marks, red for hardware-free tests.')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).parent/'results'/'images')
    args = parser.parse_args()
    service = ScanService(args.output_dir, CameraClient(args.camera_preview),
                         defective_color=args.defective_color or ('red' if args.demo else 'blue'))
    service.select_camera(args.camera_source)
    live = LiveScanner(service, demo=args.demo)
    live.start()
    print(f'Cell scanner: http://127.0.0.1:{args.port} ({"demo" if args.demo else "camera"})', flush=True)
    try:
        create_app(service, live).run(host='127.0.0.1', port=args.port, threaded=True, debug=False)
    finally:
        live.stopped.set()
        with live.condition:
            live.condition.notify_all()


if __name__ == '__main__':
    main()
