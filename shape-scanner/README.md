# Lab Shape Scanner

For the new configurable red-or-blue/green cell scanner, camera MCP tools, pixel integration contract,
and hardware-free mode, see [CAMERA_VISION.md](CAMERA_VISION.md).
Run `python run_cells.py` for its separate live page on port 8767. The original
triangle/quadrilateral app below remains available on port 8766.

A separate local app that labels closed black-outline triangles and quadrilaterals
on light paper. A square is included in the quadrilateral class. No coordinates,
printer motion, learned model, or cloud service are used in this version.

## Run in VS Code

Keep `camera-control/app.py` running and its **Start preview** active. In a new
terminal:

```sh
cd '<repository>/shape-scanner'
.venv/bin/python app.py
```

Open **http://127.0.0.1:8766**. The page displays colored boxes, contour outlines,
labels, and shape counts. The camera dashboard stays on port 8765. To change ports:

```sh
.venv/bin/python app.py --port 8767 --source http://127.0.0.1:8765
```

This program only reads `/snapshot.jpg` from the existing camera server. It does
not start another RTMP receiver or change the phone's settings. Stop with Ctrl+C.

## HTTP API

- `GET /api/detections`: recent result with `ok`, `observed_at`, frame number,
  counts, and detections (`number`, `shape`).
- `GET /snapshot.jpg`: annotated recent JPEG.
- `GET /video`: annotated MJPEG preview.

An unavailable or stale frame returns HTTP 503, not a successful empty detection.
`observed_at` is the Mac processing time, not the iPhone's shutter timestamp.
Numbers on the image are assigned left to right per frame, not persistent IDs.
The shared detector processes up to about five camera frames per second.

```python
import json
from urllib.request import urlopen
with urlopen('http://127.0.0.1:8766/api/detections', timeout=5) as response:
    observation = json.load(response)
print(observation['counts'])
```

## MCP for agents

`mcp_server.py` provides two tools using the official MCP Python SDK:

- `detect_shapes()`: structured current detections and counts.
- `get_annotated_image()`: the annotated JPEG as an MCP image block.

The MCP server uses stdio. Let your agent host launch it; running it by hand
waits silently for protocol input. A ready-made launch configuration with absolute
paths is in `mcp-config.json`. Copy its server entry into the MCP configuration
format of your agent host. This file does not register a server automatically.
Keep both the camera preview and scanner running. Override the scanner URL using
`SHAPE_SCANNER_URL` when necessary.

References: [official MCP SDK](https://github.com/modelcontextprotocol/python-sdk),
[stdio transport](https://py.sdk.modelcontextprotocol.io/run/),
[image tools](https://py.sdk.modelcontextprotocol.io/servers/media/).

## Detection conditions and limitations

Use closed dark pen outlines on light paper, keep each entire shape in view,
with an interior noticeably brighter than its stroke. The method checks nested
contours, three/four corner approximations, convexity, and ink/paper contrast.
It tolerates moderate drawing irregularity and camera angle. Severe perspective,
blur, glare, touching shapes, broken lines, very small shapes, or similar hardware
outlines may cause missed/false detections. These are geometric detections, not
calibrated confidence probabilities or a general object classifier.

## Install / verify

The separate `.venv` is already prepared. To recreate it:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest -v test_scanner.py
```

For a bold outline around the 200×200 mm board, use **Use thick border** and check
its four labels before applying. The scanner then follows the freshly detected
marker centerlines in each frame. See CAMERA_VISION.md for orientation, visibility
and accuracy limits. Restart run_cells.py after installing these changes.

Cell scanner camera selection: open http://127.0.0.1:8767 and choose **iPhone** or
**localhost:8080**. The latter uses the local IP Webcam server's `/shot.jpg`.
You can start directly with `.venv/bin/python run_cells.py --camera-source ip_webcam`.
Each input has its own board reference; confirm calibration when first using it.
See `CAMERA_VISION.md` for the HTTP and MCP source-selection tools.
