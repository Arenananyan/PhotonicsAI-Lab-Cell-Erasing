# iPhone camera control and live preview

Tested with the connected iPhone 16 Pro running Blackmagic Camera.

## Start

Keep Blackmagic Camera in the foreground with Remote Camera mode and HTTP Server enabled.
The phone and Mac must be reachable on the same local network.

```sh
cd '<repository>/camera-control'
.venv/bin/python app.py --host PHONE_IP --configure-stream
```

Open http://127.0.0.1:8765 and press **Start preview**. Start preview reconnects any stale phone stream and configures the current Mac address automatically. Stop ends the phone's outgoing stream; keep the program running to restart it. Ctrl+C also stops a stream started by this application.

`--configure-stream` finds the Mac's current local address, adds a `Lab Scanner Local RTMP` destination on the phone, and selects it. It refuses to reconfigure while another stream is active. The previous destination is preserved in `previous_stream.json`. The camera's IP can change when reconnecting to Wi-Fi; pass the address shown by Blackmagic's HTTP Server screen.

The interface provides live video, camera zoom, manual focus, autofocus, ISO, white balance and image saving. Unsupported settings are reported as camera API errors. ISO/white-balance values can change again if the camera's automatic modes remain active.

## Use from Python

For interactive terminal control, open another terminal in this directory:

```sh
.venv/bin/python terminal.py --host PHONE_IP
```

Enter `set zoom 0.3`, `set focus 0.7`, `set iso 400`, `set wb 5500`,
`autofocus`, or `status`. Use `exit` to leave. This connects directly to the
phone and can run alongside the preview app. Use the phone's current HTTP Server IP.

See `example.py`. The REST client is independent of the preview app and uses only Python's standard library:

```python
from blackmagic_camera import BlackmagicCamera
camera = BlackmagicCamera('PHONE_IP')
print(camera.status())
camera.set_zoom(0.03)
camera.set_focus(0.7)
camera.autofocus()
```

Zoom and focus use the camera's normalized 0..1 scales. Zoom is not a magnification factor. Focal length returned by the API is the phone's reported value; this does not establish that all zoom is optical. Manual focus is not a distance in metres.

With the preview server running, `http://127.0.0.1:8765/snapshot.jpg` returns a recent JPEG. Stale or missing video returns an error instead of an old frame. Save current image stores a JPEG in `captures/`. This is a frame from the video stream, not a native full-resolution still photo. Preview/snapshots are currently resized to fit 1280 × 1280, at approximately 10 fps. Network/decoder latency is not measured; scanner movement must allow settling and stream delay before using a frame.

## Connections

- Camera controls: HTTPS REST at the phone's port 4444.
- Video: iPhone publishes RTMP to this Mac's port 1935; PyAV decodes it.
- Dashboard and JPEG/MJPEG API: loopback only, port 8765.
- No cloud destination is used. Camera HTTPS uses a dedicated context accepting the phone's self-signed certificate. RTMP is unencrypted and intended for a trusted local network.

Dependencies are installed in this directory's `.venv`. To recreate it:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Reference: the YAML files under `docs/` were downloaded directly from this phone's `/control/documentation.html` endpoint.

## Digital viewing zoom and arrows

The camera page now uses `/video/view`: a digital crop resized for viewing. Use
**Digital view zoom** (1–8×), arrows, and **Full frame**. Arrows move the viewing
window toward the requested direction; at 1× there is no room to pan.
This does not change the iPhone lens or the scanner input. The separate **Phone
camera zoom** slider still changes the actual camera and full-frame feed.

- `GET /api/view`: normalized center and crop state.
- `POST /api/view`: local control header, JSON `{"action":"zoom","value":2}`,
  `{"action":"pan","direction":"right","step":0.2}`, or `{"action":"reset"}`.
- `GET /snapshot-view.jpg`: digital viewing JPEG; `X-View-Metadata` contains exact
  crop pixel bounds, original/output dimensions and the mapping to full pixels.
- Existing `/snapshot.jpg` and `/video` remain full-frame for the scanner.

Pan step is a fraction of the visible crop width/height; ranges are clamped to
image bounds. Digital zoom does not add optical detail. Source view state is
shared between the page and LLM tools. Tests: `.venv/bin/python -m unittest -v test_viewport.py`.
