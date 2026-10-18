# Camera vision integration contract

This version supports **red defective / green healthy** for the supplied tests,
and **blue defective / green healthy** for your actual marker setup. These are
labels for colored test regions, not medical diagnosis. Live mode defaults to
blue; demo and one-shot modes default to red. Override with `--defective-color red`
or `--defective-color blue`. No grades or printer control; physical fields require explicit board calibration. No paid APIs, trained weights, or additional hardware are used.

The existing `camera-control` app and the original shape scanner are preserved.
New modules are under `camera_vision/`, with a separate entry point `run_cells.py`.
Git branch: `feature/camera-vision`. `shape-scanner` was not previously a Git
repository; it was initialized locally on that branch without a remote or commits.

## Board coordinates and area — version 2.0

The new user request authorizes calibrated printer-plane coordinates in addition
 to the original pixel contract. Pixel fields remain unchanged. `schema_version`
is now `2.0`; clients must accept the updated schema.

The user confirms that the paper origin equals the printer origin. X increases
right, Y increases up. The marked outer board spans 200×200 mm; large marked cells
are 50 mm and the small grid is now **4 mm**, replacing the earlier 5 mm reference.
The homography is measured using the four outer coordinate-grid intersections,
not the paper edges or an assumed pixels-per-mm ratio.

Each detection adds:

- `printer_coordinates_mm`: `{x,y}` at the centroid of the transformed contour.
- `area_mm2`: area enclosed by the transformed outer contour, including holes.
- `calibration_id` and `calibration_status` for traceability.

If uncalibrated, the input is not a camera frame, the grid cannot be reidentified,
the region is clipped or outside the calibrated board, physical
fields are **null**. Pixel values remain available. No printer commands are sent.

### Calibrate again

On the live page, press **Calibrate board**. A raw snapshot is frozen. Click in
order: (0,0) bottom-left; (200,0) bottom-right; (200,200) top-right; (0,200) top-left.
Click the thick coordinate-grid intersections, then **Apply calibration**.
This sets the absolute board reference once. The camera may then translate,
rotate, tilt, or zoom while the same labelled board remains visible. Each frame
matches reference grid/axis features with SIFT, fits a RANSAC transform, verifies
both families of visible 50-mm lines, and refines their intersections. It does
not reuse the reference pixel-to-mm matrix after camera movement.

At least ten consistent feature matches, six axis/border reference points, wide
coverage in both board directions, and at least three verified large lines in
each direction are required. These checks can fail under blur, glare, obstruction,
or an interior-only crop. Such frames return null mm fields and pause board-only
detections; the UI shows dashes rather than claiming that no objects exist.
Reinitialization is needed if the reference board/layout is replaced, not merely
because the camera moves.

Endpoints: `GET /api/calibration`, `POST /api/calibration` with
`{"frame_id":"...","pixel_points":[[x0,y0],[x1,y1],[x2,y2],[x3,y3]]}`, and
`DELETE /api/calibration` to disable. Reference snapshots persist independently.
Calibration snapshots are append-only in `results/images/calibration/`; `active.json`
is only the current configuration pointer. It never replaces experiment images.

Additional MCP tools: `scanner_get_calibration` and `scanner_calibrate_board`.
Total camera/scanner tools: 15. Existing scanner tools return the version 2 result.

These measurements are approximate: accuracy depends on actual printed dimensions,
corner selection, flatness, lens distortion, and correct object/board coplanarity.
Four-point reprojection alone is not an independent accuracy check. Use a known
reference object to evaluate real measurement error. The per-frame `calibration` object records `mode=dynamic_reference_grid`,
matched point counts, grid-line support, refined intersection count, the current
`image_to_board_homography`, and `board_polygon_px`. Objects whose centers map
outside the calibrated 0–200 mm board are excluded, including the printer display.
This is reference-based recognition, not OCR of an arbitrary unseen grid. A plain
repeating interior lattice does not establish an absolute origin. The original
labelled grid needs to remain sufficiently visible and recognizable.

## Installation

Requires Python 3.10+ and the pinned package wheels for your platform. Tested here
with Python 3.14 on Apple Silicon. Existing `.venv` is already prepared:

```sh
cd '<repository>/shape-scanner'
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

The iPhone preview has its own environment and requirements under `camera-control`.
The scanner uses OpenCV color segmentation; no training or cloud credentials.

## Live iPhone mode

1. Keep Blackmagic Camera open, HTTP Server and Remote Camera enabled. Mac and
   phone must be reachable on the same local network.
2. In one terminal:

   ```sh
   cd '<repository>/camera-control'
   .venv/bin/python app.py --host PHONE_IP
   ```

3. Open http://127.0.0.1:8765 and press **Start preview**. Use the current phone
   IP from Blackmagic if it changes.
4. In another terminal:

   ```sh
   cd '<repository>/shape-scanner'
   .venv/bin/python run_cells.py
   ```

5. Open http://127.0.0.1:8767. You can also start the phone preview from this page.

The phone's HTTPS REST address is `https://PHONE_IP:4444`; **it is not an
image-stream URL**. The preserved preview receives RTMP and exposes a recent JPEG
at `/snapshot.jpg`. The new scanner reads this JPEG via loopback HTTP, never opens
a second RTMP receiver. Custom preview endpoint: `--camera-preview http://127.0.0.1:8765`.
All new web/MCP HTTP servers bind to loopback only.

The UI draws boxes and centroid markers, labels both classes, shows pixel centers
and frame ID, and lets you upload an image or **Analyze & save experiment**.
Live analysis stays in memory and does not create files continuously.

## Hardware-free mode

No phone, camera preview, or network camera calls are needed:

```sh
.venv/bin/python run_cells.py --demo
```

If live mode is already on 8767, run a second demo on 8769:

```sh
.venv/bin/python run_cells.py --demo --port 8769
```

The dropdown offers `one_red`, `multiple_red`, `no_red`, `mixed`, `noise`, and
`dim`. Raw capture in demo returns synthetic frames. Camera status and controls
return `CAMERA_DISABLED`; they do not access hardware.

For one-shot analysis with no web server:

```sh
.venv/bin/python scan_image.py --scene mixed
.venv/bin/python scan_image.py --image '/absolute/path/to/input.png'
```

Each one-shot/explicit scan saves its experiment. Select another output directory
with `--output-dir`; the default is `shape-scanner/results/images/`.

## Coordinates and frame identity

- `coordinate_space` is always `image_pixels`.
- Origin is the image's top-left corner; x grows right, y grows down.
- `bbox` is `{x, y, width, height}`. Pixel extent is half-open:
  `[x, x+width) × [y, y+height)`.
- `center` is the contour centroid `{x, y}` in pixels, potentially fractional.
- `area_px2` is the area enclosed by the segmented outer contour in pixel²,
  including internal holes. It is approximate, not a physical measurement.
- `touches_image_edge` warns of an incomplete/clipped region.
- Coordinates refer to the **delivered JPEG dimensions**, shown in `frame.width`
  and `frame.height`. The existing camera preview resizes to fit 1280×1280;
  these are not necessarily native iPhone sensor pixels.
- Each acquisition gets a UUID `frame_id`, repeated in every detection. It
  identifies this app's acquired image, not a camera hardware frame counter.
- `acquired_at` is the Mac's acquisition time in UTC, not the exposure timestamp.
- Every analysis gets its own `analysis_id`; rescanning the same saved frame
  retains `frame_id` and creates a new `analysis_id` and annotated output.
- Live IDs are ephemeral. Save first using `camera_capture_frame` to hand an exact
  reusable frame to another agent. Do not treat detection IDs as persistent tracks.
- `defective_color` records the active red/blue configuration.
- `reference_grid.cell_side_mm` is your updated 4 mm reference.
  `used_for_calibration` indicates valid board calibration; scale is determined
  by the explicit 200×200 mm board points, not automatically from small squares.
- The calibration/printer team must perform all transformations to physical space.

## HTTP endpoints

| Method | Endpoint | Contract |
| --- | --- | --- |
| GET | `/api/live` | Current read-only `ScanResult`; paths are null, unavailable => 503. |
| GET | `/api/live.jpg` | Current annotated JPEG; `X-Frame-ID` header. |
| GET | `/video` | Annotated MJPEG stream. |
| GET | `/api/config` | Mode, synthetic scenes, camera preview URL. |
| POST | `/api/capture` | Save raw image independently; returns `FrameInfo`. |
| POST | `/api/scan` | JSON `{}` acquires/analyzes/saves; `{"frame_id":"..."}` analyzes that saved frame. |
| POST | `/api/scan-upload` | Multipart `image` field; saves/analyzes without camera. |
| POST | `/api/demo-scene` | `{"scene":"mixed"}`; only in demo mode. |
| GET | `/api/frames/<frame_id>/raw` | Exact saved raw JPEG/PNG. |
| GET | `/api/frames/<frame_id>/analyses/<analysis_id>/image` | Exact saved annotated PNG. |
| GET | `/api/camera/status` | Existing preview's camera/settings state. |
| POST | `/api/camera/control` | `{"action":"zoom","value":0.3}` or start/stop/focus/autofocus/iso/white_balance. |

Use JSON content type for JSON POSTs. Upload limit is 20 MiB; decoded image limit
is 30 megapixels. Errors return `{ "ok": false, "error": { "code": "...",
"message": "..." } }`. An unavailable camera returns 503, invalid images 422,
invalid JSON requests 400, missing IDs 404, and storage errors 500. Failure is
never represented as a successful empty detections list.

## JSON response schemas

Machine-readable schemas are generated from the same Pydantic models used by MCP:

- `schemas/frame.schema.json`: `FrameInfo`.
- `schemas/scan-result.schema.json`: `ScanResult`, including every detection.
- `schemas/error.schema.json`: HTTP errors.

Regenerate with `.venv/bin/python schema_export.py` after model changes.
Essential scan-result shape (identifiers abbreviated here for explanation):

```json
{
  "schema_version": "2.0",
  "ok": true,
  "frame_id": "<32-character UUID hex>",
  "analysis_id": "<32-character UUID hex>",
  "frame": {
    "frame_id": "<same frame ID>",
    "acquired_at": "<UTC acquisition time>",
    "source": "camera",
    "width": 1280,
    "height": 720,
    "raw_image": "<absolute saved path or null for live>"
  },
  "coordinate_space": "image_pixels",
  "pixel_origin": "top_left",
  "defective_color": "red",
  "reference_grid": {"cell_side_mm": 4.0, "source": "user_provided", "used_for_calibration": false},
  "counts": {"defective": 1, "healthy": 0},
  "detections": [{
    "frame_id": "<same frame ID>",
    "detection_id": "<frame ID>:1",
    "label": "defective",
    "color": "red",
    "bbox": {"x": 138, "y": 118, "width": 85, "height": 85},
    "center": {"x": 180.0, "y": 160.0},
    "area_px2": 5400.0,
    "touches_image_edge": false
  }],
  "annotated_image": "<absolute saved PNG path or null for live>",
  "result_json": "<absolute saved JSON path or null for live>",
  "method": "HSV color segmentation and contour geometry",
  "warnings": []
}
```

The numbers above are illustrative synthetic pixel values, not measurements of
an actual iPhone scene. Clients should consume actual returned values only.

## MCP tools

`cells_mcp_server.py` is independent of the original `mcp_server.py`.
`cells-mcp-config.json` contains the stdio launch entry. Copy the entry into your
agent host's MCP settings; no automatic registration is performed.
The environment variable `CAMERA_VISION_URL` selects the running scanner (default
`http://127.0.0.1:8767`; use 8769 for a second demo).

| Tool | Arguments | Result |
| --- | --- | --- |
| `camera_get_status` | none | Structured `preview` camera status/settings object. |
| `camera_capture_frame` | none | `FrameInfo` with raw saved independently. |
| `camera_get_frame_image` | `frame_id` | MCP image block for the exact raw frame. |
| `camera_start_preview` | none | `{ok:true}`; reconnect outgoing phone stream. |
| `camera_stop_preview` | none | `{ok:true}`; stop outgoing phone stream. |
| `camera_set_zoom` | `value` | `{ok:true}`; normalized 0..1, not optical zoom factor. |
| `camera_set_focus` | `value` | `{ok:true}`; normalized 0..1, not focus distance. |
| `camera_autofocus` | none | `{ok:true}`. |
| `scanner_scan_current_frame` | none | Saved `ScanResult` from camera/demo acquisition. |
| `scanner_scan_saved_frame` | `frame_id` | Saved `ScanResult` using the exact captured frame. |
| `scanner_analyze_image` | `image_path` | Saved `ScanResult` from a readable local file; no hardware. |
| `scanner_get_live_detections` | none | Read-only `ScanResult`; no files saved. |
| `scanner_get_annotated_image` | `frame_id`, `analysis_id` | MCP image block for the exact saved analysis. |

MCP errors have `isError=true` with the explicit error code/message in their
text content. The SDK advertises input/output schemas in `tools/list`.
The host normally launches stdio; starting the script manually waits for protocol
input. Optional loopback Streamable HTTP:

```sh
.venv/bin/python cells_mcp_server.py --http --port 8768
```

Connect an MCP client to `http://127.0.0.1:8768/mcp`.

## AI integration example

The following is a camera-free example when `run_cells.py --demo` is running.
It captures one exact raw frame and passes its ID to the scanner:

```python
import asyncio
from pathlib import Path
import sys
from mcp import Client, StdioServerParameters

async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(Path('cells_mcp_server.py').resolve())],
    )
    async with Client(params) as client:
        frame = await client.call_tool('camera_capture_frame')
        if frame.is_error:
            raise RuntimeError(frame.content)
        frame_id = frame.structured_content['frame_id']
        result = await client.call_tool('scanner_scan_saved_frame', {'frame_id': frame_id})
        if result.is_error:
            raise RuntimeError(result.content)
        data = result.structured_content
        assert data['frame_id'] == frame_id
        for cell in data['detections']:
            if cell['label'] == 'defective':
                print(frame_id, cell['center'], cell['bbox'])  # image pixels only

asyncio.run(main())
```

## Experiment outputs

All outputs are append-only under `results/images/`, excluded from Git:

- `<frame_id>.raw.jpg` or `.raw.png`: unannotated input.
- `<frame_id>.frame.json`: acquisition metadata.
- `<frame_id>_<analysis_id>.annotated.png`: boxes, centers, labels.
- `<frame_id>_<analysis_id>.result.json`: matching full result.

New files use exclusive creation; collisions raise errors instead of replacing
an earlier file. JPEG/PNG raw bytes are preserved exactly. Other supported input
formats are normalized into an unannotated PNG. An explicit capture saves raw
without needing detection. Live preview does not fill the disk with experiment
files. No automatic retention/deletion policy is applied.

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m unittest -v test_scanner.py
```

The new automated suite includes the seven requested cases: one red, multiple red,
no red, red+green, noise/lighting, invalid images, camera unavailable. It also
checks red hue wraparound, ignored blue, outlines/clipping, pixel centers, configurable blue/green mode and grid metadata, dark hardware reflections, repeated
frame analysis, separate raw/annotated saving, no overwriting, demo without camera,
HTTP validation, and actual stdio MCP acquisition→scan→image/error calls. Tests
use temporary output directories and do not alter earlier experiments.

## Limitations

This is deterministic HSV segmentation, not a trained medical or general object
classifier. Saturated red/blue/green background objects on light surfaces may also be detected.
A relative paper-brightness check filters many colored reflections on dark hardware.
Thin grid lines are suppressed by morphology; unusually thick/saturated grids can
still affect segmentation. Similar
colors, low saturation, glare, severe blur, touching regions, incomplete outlines,
and tiny marks can produce misses/merged regions. Objects smaller than the default
80 pixel² contour threshold are filtered as noise. Centers/areas depend on the
segmented contour. No temporal object tracking or calibrated probability is
reported. Camera movement and zoom trigger a fresh per-frame transform. Insufficient visible grid/axis evidence pauses measurements. Actual preview transport latency is not calibrated.

## Fixed camera: digital view tools

The camera is now physically fixed. Digital viewing zoom/pan lives in
`camera-control` and leaves the scanner's full `/snapshot.jpg` input unchanged.
Refresh the camera page to see the **Digital view zoom** slider, four arrows and
**Full frame**. The phone zoom control is separate and still changes the full
camera feed; use the digital view controls for inspection.

Five additional MCP tools (20 total):

- `camera_get_view()` returns shared zoom, normalized full-frame center/crop.
- `camera_set_view_zoom(zoom)` accepts viewing magnification 1–8.
- `camera_pan_view(direction, step=0.2)` accepts left/right/up/down. Step is a
  fraction of the current visible crop, not printer distance or source pixels.
- `camera_reset_view()` returns to centered 1× full-frame viewing.
- `camera_capture_view()` saves the current crop for LLM inspection and returns
  `{frame, view}`; then `camera_get_frame_image(frame.frame_id)` returns that image.

`view.crop_pixels` is the source-image crop `{x,y,width,height}`. For an LLM image
point `(u,v)`, map back to the full image using:

```
source_x = crop_pixels.x + u * crop_pixels.width / output_width
source_y = crop_pixels.y + v * crop_pixels.height / output_height
```

The crop is explicitly marked `FrameInfo.source="view"`; it cannot silently
inherit printer calibration. Scanner current/capture tools continue using complete
frames. The viewing crop has its own identifier and is saved independently;
metadata provides an image-coordinate transform, not new printer coordinates.

Proxy endpoints: GET/POST `/api/camera/view`, POST `/api/camera/view/capture`.
Demo mode disables hardware/view access. Camera-control paths: `/api/view`,
`/video/view`, `/snapshot-view.jpg` (metadata header). Camera and scanner servers
must both be running for the MCP view tools. Limits, boundary clamping, crop mapping
and full-frame independence are covered by `camera-control/test_viewport.py`.

## Confirmed printer origin offset

The board (0,0) corresponds to printer (9,8) mm; positive axes agree.
`printer_coordinates_mm` uses X=board_X+9, Y=board_Y+8.
The image-to-board homography and board filtering stay in board coordinates.
Areas are unchanged by this translation. Pixel centers remain unchanged.
Calibration responses expose `printer_origin_mm`; saved earlier experiments retain their original data.
This mapping does not command printer movement.

## Stable frozen targets

POST `/api/targets/lock` or MCP `scanner_lock_target` takes `label` (defective/healthy),
`stable_seconds` (default 2, range .5..10), `tolerance_mm` (default 1, range .1..5),
and `timeout_seconds` (default 10, greater than stability window, maximum 15).
The defaults are configurable engineering criteria, not measured accuracy.
Exactly one matching calibrated cell is required initially; subsequent frames must
match uniquely within 5 mm. All observed pairwise XY distances must be within the
requested tolerance. Missing/invalid calibration resets the consecutive window.
At least three distinct frames are required. Camera failure cannot produce a target.
The frozen result uses the latest accepted frame, not an averaged invented frame;
it includes XY, area, timestamps, supporting frame IDs, sample count and calibration ID.
Target JSON and the latest annotated evidence are saved exclusively under
`results/images/targets/`. Live frame IDs are provenance, not saved raw-image handles.
This does not estimate absolute accuracy or authorize movement. After a cell/grid
change reacquire; after a printer move, let the board settle and reacquire to compare.
Use the dashboard's **Lock stable target** button to try it; failure is explicit.

### Largest-blue agent selection and frame tracking

`scanner_lock_target` now supports `selection="largest"` (default remains unique).
It ranks calibrated blue cells by mm², rejects top areas within 5%, and verifies
that the winning cell remains uniquely associated with the previous position.
These criteria prevent silently switching cells in a near tie; they are not
medical classifications or measured accuracy thresholds.
Dynamic grid recognition can fall back to forward/backward optical flow from
its most recent verified frame (at most 1 second old). It requires sufficient
inlier coverage including board borders and verifies the 50-mm lines in the new
frame. Failed tracking never returns the cached transform as a fresh measurement.

## Thick marker border reference

The operator's outer 0–200 mm marker rectangle can be used instead of SIFT/grid
feature matching. Select **Use thick border**, inspect the proposed labels in
bottom-left, bottom-right, top-right, top-left order, then **Apply calibration**.
The four side centerlines define the existing 200×200 mm plane; printer XY is
still board XY+(9,8) mm and cell area is computed after perspective correction.
The reference mode persists in active calibration and restores after restart.

Every frame independently detects contours or thick line fragments, fits the
center of the ink stripe and intersects the four lines. Small reflection gaps
can pass only with sufficient fresh side support. Thin interior grid partitions
are discarded only when contained in a larger verified outline and distinctly
thinner than its parallel sides. Missing/ambiguous borders fail closed; no stale
homography substitutes for a lost outline. A blue/purple outline is excluded
from cells, while colored islands inside a closed colored frame are preserved.
No physical printer command is part of detection or calibration.

Keep all sides visible and the marks coplanar. A symmetric unlabelled square
cannot determine which corner is (0,0) after 90°/180° rotation; confirm the actual
axis labels initially and keep their upright orientation. Re-establish the
reference after rotating the paper/camera. Large changes of the reference edge
angles are rejected. Ink thickness and hand-drawn line curvature limit accuracy;
this does not certify physical machine alignment.

- POST `/api/calibration/border` `{frame_id}` proposes corners and diagnostics;
  it does not activate a calibration.
- POST `/api/calibration` `{frame_id,pixel_points,tracking_mode:"thick_border"}`
  applies the confirmed reference. Existing `dynamic_reference_grid` is preserved.
- MCP `scanner_detect_board_border(frame_id)` exposes the proposal.
- MCP `scanner_calibrate_board(...,tracking_mode="thick_border")` applies it.
- Live calibration metadata uses mode `thick_border`, four `side_support` values,
  `stroke_width_px`, current `board_polygon_px` and `image_to_board_homography`.

The scanner MCP now exposes 22 tools. Both calibration tools return the current
printer origin from the service; earlier (10,-20) metadata is no longer hardcoded.

## Select iPhone or IP Webcam

The scanner page has **iPhone** and **localhost:8080** buttons. The iPhone
continues to use the camera-control server (`--camera-preview`, default
`http://127.0.0.1:8765/snapshot.jpg`). IP Webcam uses the verified local endpoint
`http://127.0.0.1:8080/shot.jpg`; its server must already be running on this Mac.
There is no automatic fallback to a different camera on failure.

Start directly with IP Webcam:

```sh
.venv/bin/python run_cells.py --camera-source ip_webcam
```

Both inputs use full frames and the same cell detector. iPhone-specific controls
and digital-view tools are unsupported on IP Webcam (explicit
`UNSUPPORTED_CAMERA_CONTROL` error); use its linked camera page instead.
Switching clears the current live image/results. Reacquire agent targets after
changing input. Each camera keeps an independent board calibration. For the
first use of a camera, use **Use thick border** and confirm the labelled board
orientation before consuming printer coordinates. Existing iPhone calibration
is retained; IP Webcam references live under `results/images/calibration/ip_webcam/`.
Selection defaults to iPhone on restart unless `--camera-source` is supplied.
Legacy saved camera frames without `camera_id` belong to the iPhone.

HTTP contract:

- `GET /api/camera/source` returns
  `{"selected":"iphone","sources":[{"id":"iphone","label":"iPhone","preview_url":"http://127.0.0.1:8765","controls_supported":true},{"id":"ip_webcam","label":"localhost:8080","preview_url":"http://127.0.0.1:8080","controls_supported":false}]}`.
- `POST /api/camera/source` with `{"source":"ip_webcam"}` or
  `{"source":"iphone"}` returns the same selection schema. It changes the
  scanner input only; no printer command is sent. Invalid IDs return
  `INVALID_CAMERA_SOURCE`; demo mode rejects hardware selection.
- `FrameInfo.camera_id` is an optional string (`iphone` or `ip_webcam` for new
  camera frames, null for non-camera frames). Results retain their exact frame ID.
- MCP `camera_get_sources()` lists inputs; `camera_select_source(source)` selects
  one with the same semantics as HTTP. Other scanner tools use that selected input.

Camera-source tests use synthetic images and mocked acquisition to cover endpoint
selection, invalid/unavailable images, unsupported controls, validation, demo
isolation, calibration persistence and in-flight switching without old results.


## Stationary target reliability

For thick-border tracking, the confirmed planar reference now filters rectangles
with incompatible side lengths/angles before expensive fitting. Bed translation
is unrestricted; all four accepted corners are still measured in the current
frame. No previous homography is substituted for an unavailable current border.
Two compatible board outlines remain ambiguous. A substantial camera pose/scale
change may require setting the reference again.

Border processing batches stripe statistics and reuses grayscale/paper masks
instead of recomputing them for every candidate. `/api/live` and `/api/live.jpg`
read the last completed fresh result without waiting for the next frame's source
lock; source switching still clears old results and serializes publication.
The three-distinct-frame requirement, 1 mm default target tolerance, stale-frame
checks and calibration-loss rejection remain in place.
