"""Interactive camera controls: python terminal.py --host PHONE_IP."""
import argparse
import json
import shlex

from blackmagic_camera import BlackmagicCamera, CameraError

HELP = '''Commands:
  set zoom 0.3       (0..1)
  set focus 0.7      (0..1)
  set iso 400
  set wb 5500        (kelvin)
  autofocus
  status
  help
  exit'''


def execute(camera, command):
    parts = shlex.split(command)
    if parts == ['status']:
        return camera.status()
    if parts == ['autofocus']:
        return camera.autofocus()
    setters = {'zoom': camera.set_zoom, 'focus': camera.set_focus,
               'iso': camera.set_iso, 'wb': camera.set_white_balance,
               'white-balance': camera.set_white_balance}
    if len(parts) == 3 and parts[0] == 'set' and parts[1] in setters:
        value = float(parts[2])
        if parts[1] in ('iso', 'wb', 'white-balance'):
            if not value.is_integer() or value <= 0:
                raise ValueError('Use a positive whole number.')
        return setters[parts[1]](value)
    raise ValueError('Unknown command. Type help.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    args = parser.parse_args()
    camera = BlackmagicCamera(args.host)
    print(f'Camera: {camera.base_url}\n{HELP}')
    while True:
        try:
            command = input('camera> ').strip()
            if command in ('exit', 'quit'):
                break
            if not command:
                continue
            if command == 'help':
                print(HELP)
                continue
            result = execute(camera, command)
            print(json.dumps(result, indent=2) if result is not None else 'OK')
        except (CameraError, ValueError) as exc:
            print(f'Error: {exc}')
        except (EOFError, KeyboardInterrupt):
            print()
            break


if __name__ == '__main__':
    main()
