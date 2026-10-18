"""Analyze one image or a synthetic scene without starting camera hardware."""
import argparse
import json
from pathlib import Path
from camera_vision.errors import VisionError
from camera_vision.service import ScanService
from camera_vision.synthetic import SCENES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--image', help='Readable local image path.')
    source.add_argument('--scene', choices=SCENES)
    parser.add_argument('--defective-color', choices=('red', 'blue'), default='red')
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).parent/'results'/'images')
    args = parser.parse_args()
    try:
        service = ScanService(args.output_dir, defective_color=args.defective_color)
        result = service.scan_file(args.image) if args.image else service.scan_demo(args.scene)
        print(result.model_dump_json(indent=2))
    except VisionError as exc:
        print(json.dumps(exc.as_dict()))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
