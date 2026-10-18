"""Blackmagic Camera REST client. Importable; no connection is made on import."""
import argparse
import json
import ssl
import urllib.error
import urllib.request


class CameraError(RuntimeError):
    pass


class BlackmagicCamera:
    def __init__(self, host='127.0.0.1', port=4444, timeout=5):
        self.base_url = f'https://{host}:{port}/control/api/v1'
        self.timeout = timeout
        # The local Blackmagic server uses a self-signed certificate.
        # This context is used only for this explicit camera connection.
        self.context = ssl._create_unverified_context()

    def request(self, path, method='GET', data=None, xml=None):
        payload = xml.encode() if xml is not None else (json.dumps(data).encode() if data is not None else None)
        req = urllib.request.Request(self.base_url + path, data=payload, method=method,
            headers={'Content-Type': 'application/xml' if xml is not None else 'application/json'})
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=self.timeout) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            message = exc.read().decode(errors='replace')
            raise CameraError(f'{method} {path}: HTTP {exc.code}: {message}') from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CameraError(f'Cannot reach camera at {self.base_url}: {exc}') from exc

    def status(self):
        return {name: self.request(path) for name, path in {
            'zoom': '/lens/zoom', 'focus': '/lens/focus', 'iso': '/video/iso',
            'white_balance': '/video/whiteBalance', 'stream': '/livestreams/0'}.items()}

    def set_zoom(self, value):
        """Normalized camera zoom, 0..1; NOT a magnification such as 2x."""
        self._normalised(value)
        return self.request('/lens/zoom', 'PUT', {'normalised': value})

    def set_focus(self, value):
        """Manual lens position, 0..1; not a distance in metres."""
        self._normalised(value)
        return self.request('/lens/focus', 'PUT', {'normalised': value})

    def autofocus(self):
        return self.request('/lens/focus/doAutoFocus', 'PUT', {})

    def set_iso(self, value):
        return self.request('/video/iso', 'PUT', {'iso': int(value)})

    def set_white_balance(self, kelvin):
        return self.request('/video/whiteBalance', 'PUT', {'whiteBalance': int(kelvin)})

    def start_stream(self):
        return self.request('/livestreams/0/start', 'PUT')

    def stop_stream(self):
        return self.request('/livestreams/0/stop', 'PUT')

    @staticmethod
    def _normalised(value):
        if not 0 <= value <= 1:
            raise ValueError('Value must be between 0 and 1.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ['status', 'autofocus']:
        sub.add_parser(name)
    for name in ['zoom', 'focus', 'iso', 'white-balance']:
        child = sub.add_parser(name)
        child.add_argument('value', type=float)
    args = parser.parse_args()
    camera = BlackmagicCamera(args.host)
    if args.command == 'status':
        result = camera.status()
    elif args.command == 'autofocus':
        result = camera.autofocus()
    else:
        method = {'zoom': camera.set_zoom, 'focus': camera.set_focus,
                  'iso': camera.set_iso, 'white-balance': camera.set_white_balance}[args.command]
        result = method(args.value)
    print(json.dumps(result if result is not None else {'ok': True}, indent=2))


if __name__ == '__main__':
    main()
