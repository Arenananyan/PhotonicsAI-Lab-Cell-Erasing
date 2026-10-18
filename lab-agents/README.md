# Lab Agents — natural-language tasks with bounded execution

Groq interprets Armenian/English requests and proposes `interpret_request`,
`select_targets`, `recommend_actions`, and `continue_task` function calls. The host validates these
proposals against actual scanner measurements and the operator-approved scope.
Production has no keyword command parser. `--demo` deliberately uses scripted
fixtures and does not demonstrate language-model accuracy.

Supported examples:

- `Մաքրիր ամենամեծ կապույտ բջիջը։` / `Clean the largest blue cell.`
- `Մաքրիր բոլոր կապույտները։` / `Clean all green cells.`
- `Մաքրիր ամենափոքր կանաչ բջիջը։`
- `Go to X=100 Y=120 Z=50.`
- `Inspect the cells.`
- `Գնա «տուն»։` / `Return home.` — configured HOME (209,208,100), no scan or wipe and no G28.
- `Ցույց տուր բջիջները մեծից փոքր՝ կոորդինատներով։` — blue and green are listed separately by measured area.
- `Եթե կապույտները 2-ից շատ են, մաքրիր ամենամեծ կապույտը։` — one measured condition, then the usual path approval.
- `If total green area is greater than total blue area, clean all green cells.`
- `Մաքրիր ամենամեծ կանաչ բջիջին ամենամոտ կապույտ բջիջը։`
- `Որքա՞ն է ամենամեծ կապույտ և ամենամեծ կանաչ բջիջների հեռավորությունը։`
- `Գնա տուն, հետո նորից դիտիր տախտակը։`
- `Find the biggest green cell and from that point find the nearest blue cell.` — read-only composed selection.
- `Find the biggest green cell.` followed by `Go to that point.` — resolves the selected cell in this chat, re-observes and previews a move above it at Z100.

Find/locate/show requests now have explicit measured selections. They do not imply
cleaning or movement. A selected-cell card shows the result independently of the
full inventory. A go/visit-cell request is a move to its measured XY at Z100;
cleaning requires a clean/erase/wipe request. Other Z values for a cell-relative
move must be clarified; fully specified absolute XYZ movement remains supported.

The dashboard sends its chat ID and up to eight prior run references. Conversation
context includes server-owned tasks, answers and measured selected targets from
that same chat. Saved completed run files can restore that context after a server
restart, without restoring approvals or resuming movement. New chats are isolated.
Browser-provided coordinates are never accepted as historical measurements.
Prior cell positions are references only: a fresh calibrated stationary view must
identify the same cell before a path is prepared, and dispatch rechecks it again.
Missing, ambiguous or differently calibrated cells ask for clarification.

Groq tool-generation errors (`400/tool_use_failed`) may use one JSON proposal
fallback with identical schema and scope validation. This never retries a printer
operation. Other errors report status/code; 429 remains an unavailable provider
response. Existing historic error logs omitted the provider error body and cannot
establish the detailed cause retroactively.

Relational requests use LLM-generated structured selectors: a largest/smallest
reference cell and a nearest blue/green target, or two largest/smallest selectors
for a distance query. The measured geometry tool calculates center-to-center XY
Euclidean distance in millimeters from one calibrated observation; it never uses
pixel distance or LLM-generated coordinates. The LLM receives the distance table
and proposes measured IDs, which are checked against the requested relation.
Distances within 3 mm of each other are ambiguous for nearest selection; size
ties within 5% remain ambiguous. Missing references and invented IDs ask for
clarification without dispatch. These are bounded relations, not arbitrary programs.

Distance queries stabilize a fresh observation, report endpoint coordinates and
distance, and draw the connecting line on the captured board image when available.
If the view is unavailable away from home, the task offers a separate home path
for approval, then re-observes. Explicit home-then-inspect requests use the same
flow. There is no automatic motion or repeated recovery loop. A bad view even
from home asks for camera/calibration correction. Ordinary status queries remain
read-only; when their view is unavailable, a suggested home-inspection command
only fills the composer. Wiping still requires its own exact-path approval.

Read-only inspections show a measured size report and up to three Groq-selected
suggestions. Suggested commands only fill the instruction box; selecting one does
not prepare or execute a path. A camera/calibration failure yields no cleaning
suggestions. Groq may select only IDs from a host-generated catalog tied to the
current observation. If the suggestion response is unavailable, the UI shows
safe catalog entries instead.

One conditional motion instruction may compare blue/green/total counts or total
blue/green measured area to a number or another metric. The comparison uses a
fresh, stable, calibrated observation while the head is at the named home
position. A false condition is reported and finishes without movement. If the
head is elsewhere, the system asks for a separate home task first; it does not
move to inspect a condition implicitly. An alternative `else` movement and
multiple conditions are not yet supported and must be clarified.

Incomplete or ambiguous instructions produce a question, not guessed coordinates.
Coordinates default to **absolute printer millimeters**. Explicit paper XY is
translated by (+9,+8); Z remains the printer's absolute Z.

## Execution contract

Prepare reads status and checks vision availability without moving hardware.
If the head is away from home, the dashboard first previews and requests approval
for that home route only. Arrival triggers recognition and prepares a separate
wipe plan, then stops for approval. If already home, recognition starts during
prepare with no positioning approval or motion.

Each target's complete measured path (including return home) is shown before
**Confirm and execute wiping**. Approval is bound to that exact path. A fresh
frame revalidates the target before dispatch; it does not silently replan the
approved coordinates. Changed, missing or stale targets block dispatch and need
a new plan. Each next target requires its own path approval. Cancelling a pending
wipe never sends that wipe. No LLM response substitutes for operator approval.

The named home is **(209,208,100)**, corresponding to paper (200,200). It is not
G28. A wipe approaches at Z100, descends to Z14.5, moves Y+10, makes one clockwise
R10 circle (72 XY segments), rises to Z100, returns X209 then Y208. Speed is
20 mm/s. A direct move rises to max(100,current Z,destination Z), moves X/Y,
then descends to the requested Z and **stays there**. All paths use the unchanged
printer MCP preview and single-use token executor. Its firmware bounds,
offsets, mesh, heater, homing, start-state and telemetry checks remain active.

Limits shown before approval: at most **20 initial targets**, **one pass each**,
**30 minutes per task**. Initial preview confirmation expires after 110 seconds;
each subsequent path is freshly previewed and dispatched within its own token
lifetime. Tokens are never reused. Changed scope requires a new confirmation.
Newly appearing cells are not added. Each original target is associated using
color and printer XY within 3 mm; missing/split/ambiguous cells cause a question.
Sizes within 5% are ambiguous for largest/smallest. At least three fresh distinct
frames over 2 seconds are required, with the existing drift/outlier guards.
The selected subset is stabilized; unrelated cells may flicker.

The LLM chooses measured IDs and their order. Deterministic validation checks
that they satisfy the approved color/ranking/all scope; it never fabricates an
alternative LLM choice. No heating, extrusion, homing or free-form G-code tools
are exposed to the model. Uncertain or failed motion is never automatically
retried. `Stop task` lets the current queued path finish and prevents the next
one; **Emergency stop** remains a separate printer shutdown requiring manual
recovery. Stopping does not promise an extra recovery/home move after failure.

## Visual verification

Saved raw before/after frames use their own current image-to-board homographies
to produce the same physical ROI at 4 pixels/mm. HSV counts **actual colored
pixels**, including residual fragments, rather than filled outer contour area.
The ROI includes the measured object bounds and at least a 12 mm radius. An ROI
outside the board, missing calibration, low ink evidence or dark occlusion is
rejected. Input frames stay in scanner `results/images/`; aligned crops have
unique directories under agents `results/evidence/`.

A separate Groq image model sees the aligned pair and measurements and returns
`clean`, `residue`, or `uncertain`. A conservative veto prevents `clean` when
more than 10% of initial colored pixels remain or evidence quality fails. This
is a visual classification, not a contact-pressure measurement or proof of
physical erasure. Reflections, nearby same-color marks and translucent material
can cause a conservative pause. Mock motion with a real camera is always
reported as unverified physical cleaning. Demo results are explicitly synthetic.

For `all` cleaning, all initial target paths are validated and displayed before
one batch approval. Each fixed path is then freshly previewed before dispatch;
the exact approved coordinates, speed, initial queue and 30-minute limit remain
binding. Usable visual evidence reporting residue or an uncertain cleaning result
is recorded without interrupting the remaining approved cells. The final summary
counts clean, residue, uncertain and skipped outcomes; completing attempts does
not imply all marks were physically erased.

Unusable/occluded evidence, missing targets, calibration loss, device errors,
expired authorization or an operator stop still pause/stop the task. Single-target
residue/uncertainty retains the question flow. A reply can finish or continue the
remaining list, **skipping the already attempted target**. Repeating that target
requires a new task and approval. Target-association questions likewise allow
skipping the missing/ambiguous cell. Recognition/intent clarifications prepare
a revised task with a new confirmation. No automatic second wiping circle.

## Install and run

The dashboard uses the supplied conversation layout from `the supplied interface reference`:
chat history, one composer for instructions and clarification replies, expandable
activity/path details, image zoom, and before/after comparison. Armenian/English
switching, measured rankings grouped by color, recommendations, conditions, target
queues, single-path approvals and explicit all-target batch approval use the backend contracts. Selecting a
starter or recommendation only fills the composer. An active task must finish or
be cancelled before opening another command. Emergency shutdown remains separate
and available while ordinary requests are pending.

Successive commands append to the same persistent conversation ribbon. Only
**New chat** (or its keyboard shortcut) starts another conversation; each sidebar
entry represents a chat. Prior responses, measurements, evidence and paths stay
visible, but old paths never expose execution controls. Existing single-command
history is migrated without discarding its entries. A scanning image card appears
only for a captured target image; request interpretation and ordinary movement
do not display a fabricated scan animation.
Each chat has a delete button with a confirmation dialog. Deletion removes only
that browser's conversation history; experiment/audit files remain saved. Chats
cannot be deleted while a task is active or a control request is pending.

Read-only inspection now saves one scanner frame and uses that same frame for
counts, area rankings, the numbered board overview and each individual cell crop.
The overview contains the whole calibrated board; cell thumbnails contain only
their measured image bounding boxes with a two-pixel margin, using raw pixels
without annotation overlays. Thumbnail numbers match the overview even when the
ranked order differs from detection order. Both views open in the image viewer.
An unavailable image is reported explicitly; measurements are never illustrated
using a different or newer frame. Display artifacts are appended under
`results/observations/` and do not affect motion planning or authorization.

Previous dashboard sources are retained in `results/ui-backups/20261017-chat-ui/`.
Restart only the agent dashboard and refresh the page after this UI update so
Flask reloads the template; no camera or printer service restart is needed.
Browser regression tests in `tests/ui_integration.cjs` require Node and Playwright
(`node --test tests/ui_integration.cjs` with Playwright available). They intercept all
API calls, use no hardware, and save desktop/mobile review images in `results/ui-review/`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Configure GROQ_API_KEY locally in `.env` or use the existing `--env-file`. Never
paste credentials into chat. `GROQ_MODEL` defaults to `openai/gpt-oss-120b`.
`GROQ_VISION_MODEL` defaults to `qwen/qwen3.8-27b`; override it with an accessible
image-input Groq model. A synthetic image preflight is performed for every wipe
task **before motion**, and an unavailable model stops preparation. Image inputs
and JSON mode follow [Groq's vision documentation](https://console.groq.com/docs/vision).
Only rectified target ROIs, not the full camera view, are sent for visual review.
The evidence worker reuses OpenCV/Numpy from sibling `shape-scanner/.venv`.

Start the scanner (8767) and its selected camera first. The camera may be iPhone
via camera-control (8765), or the existing IP Webcam source (8080). Camera-free
simulation still requires the sibling scanner/printer repositories and installed
environments for the stdio MCP clients, but not camera servers or an API key:

```bash
.venv/bin/python app.py --demo --port 8771
```

Demo supports blue/green/all/smallest fixtures and `demo move 100 120 50`.
Real Groq with simulated printer:

```bash
.venv/bin/python app.py --env-file .env
```

Open http://127.0.0.1:8770. For real preview use `--printer-mode real`. Leave the
operator's `./printerctl connect` SSH tab open and set SSH_HOST to the actual
printer IP. Real execution still requires the operator's local
`PRINTER_ALLOW_MOTION=1` plus the dashboard task approval. Startup never moves.
Restart the agent server and refresh the page after upgrading; prior in-memory
runs cannot resume. Existing camera/scanner/printer services need no changes.

### Phone access on the same Wi-Fi

Keep the existing launch options (printer mode, env file and exported SSH settings)
and append `--host 0.0.0.0 --port 8770`. The default host remains `127.0.0.1`.
From the phone open `http://COMPUTER-WIFI-IP:8770`; obtain that IP on the Mac with
`ipconfig getifaddr en0`. Do not use `0.0.0.0` or the phone's localhost as the URL.

The browser's native login dialog asks for username **lab** and the remote
password. On the first network launch a random persistent password is saved in
`.remote-access-password` with owner-only permissions. Read it in a second local
terminal with `cat .remote-access-password`. Alternatively configure a password
of at least 12 characters as `LAB_REMOTE_PASSWORD` in the environment or local
env file. Never commit/share the password file; it is ignored by Git.

Localhost connections on the Mac remain password-free. All LAN clients (phones
and other computers) need the password; forwarded headers cannot claim local
access. The gate protects images, API reads and control requests. Existing path
approval and emergency-stop behavior is unchanged. A small remote-only browser
compatibility script supports chat IDs on plain HTTP; dashboard template, styles
and main UI scripts are unchanged. This is for the local Wi-Fi network; external
internet exposure needs HTTPS and separate deployment configuration.

Phone and computer chat history remains stored in each browser separately.
The existing Scanner/Camera links still refer to the computer's localhost;
their separate services are not exposed by this option. Board images returned
inside agent responses use the agent server and work through this login.

Tests: `python -m unittest discover -s tests`; with Playwright available,
`node --test tests/lan_browser.cjs` checks a password-protected LAN HTTP origin
with an isolated fake backend and no hardware or LLM calls.

## HTTP / MCP integration

Existing scanner/printer MCP servers and schemas are unchanged. Agents use
`scanner_get_live_detections`, `scanner_scan_current_frame`, `printer_status`,
`printer_command` (position only), `preview_sequence`, `preview_position`,
`execute_sequence`, and `emergency_stop`. LLM-facing function proposals never
contain a printer token or arbitrary motor command.

Loopback POSTs require `X-Lab-Control: local`:

- `POST /api/prepare {"prompt":"..."}` → `{"run_id":"..."}` (202).
- `GET /api/runs/<id>` → state, task, limits, initial inventory, queue,
  current_target_id, results, questions, events and tool audit.
- `POST /api/runs/<id>/execute {"confirmed":true,"clear_path":true}` → 202.
  Claims the single pending task authorization; duplicate approval is rejected.
- `POST /api/runs/<id>/answer {"answer":"..."}` → 202. Claims one pending question.
- `POST /api/runs/<id>/stop-task {}` → stop after current path.
- `POST /api/runs/<id>/cancel {}` → cancel a waiting authorization/question.
- `GET /api/runs/<id>/image` → current target annotation.
- `GET /api/runs/<id>/observation/board` → the saved numbered board view.
- `GET /api/runs/<id>/observation/cells/<index>` → a crop from that exact frame.
- `GET /api/runs/<id>/evidence/<result-index>/before` or `/after` → aligned PNG.
- Existing `/api/stop {"confirmed":true}` and `/api/simulation/reset {}` retained.

Task: action (`wipe|move|home|inspect|ask|reject`), color (`blue|green|null`),
selection (`largest|smallest|all|null`), coordinates (`{x,y,z}|null`),
coordinate_system (`printer|paper|null`), optional single measured condition,
message. Result: target_id, target,
plan/execution evidence, before_frame_id, verdict, assessment, evidence with
before/after frame IDs and colored-area measurements. IDs refer to measured
initial cells; queue IDs persist when scanner per-frame detection IDs change.

States: preparing → awaiting_confirmation → executing → completed;
awaiting_answer → answering may interrupt interpretation/recognition/verification.
Terminal states also include failed, stopped, cancelled, observed and rejected.
Audit JSONL records proposals and tool requests/results as they occur; terminal
JSON is saved using exclusive creation. Restart does not auto-resume motion.

## Tests and limitations

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

Tests use scripted LLM responses, real mock MCP, synthetic images and injected
failures. They do not call a paid API or move physical hardware. They cover
multiple colors, ranking/all selection, scope/ID validation, separate home, single-target and all-target batch approvals,
expiry, stop/cancel, visual residue and failure, drift/staleness, same-plane
alignment, missing images and uncertain execution. Live Groq interpretation and
physical one-cell/multiple-cell tests are separate operator-run acceptance tests.
Before real execution verify eraser clearance, absolute contact Z and full swept
footprint. No automatic recovery, hot restart/resume, or physical cleaning claim
is inferred from mock tests.

## Questions and task-local speed

Use the same instruction box for `Որտե՞ղ է գլխիկը։`, `Կամեռան պատկեր ստանո՞ւմ է։`,
`Քանի՞ կապույտ և կանաչ բջիջ կա։`, or `What is the printer status?`.
Groq selects read-only inspection and answers from printer status/position, camera
status/source and fresh detection metadata. No approval or motion occurs for
inspection. Independent unavailable sources are reported; stale frames never count
as zero cells. The text model receives metadata, not the camera image. Recent
completed questions provide conversation context (up to six, within this server
session). Finish/cancel an active motion task before asking in the same box.

`Գնա տուն 10 մմ/վրկ արագությամբ։` or `Clean all blue cells at 15 mm/s` sets
`speed_mm_s` only for that task, including XY, Z and the circle. Unspecified/null
means 20 mm/s; accepted range is greater than zero through 30 mm/s, subject to
existing firmware checks. Speed is shown before approval, frozen in authorization
and sent to every path preview. It does not change future defaults.

## Debugged status/approval behavior (2026-10-16)

Status answers use validated JSON responses, not a forced motion tool call. If
status narration is unavailable (including Groq 429), show the actual tool facts
with an explicit LLM-unavailable warning. Task interpretation/target selection
still require the LLM and fail closed when unavailable; no motion retry is added.
An unlocated board cannot be reported as zero cells.

Approval is per displayed path: a positioning/home leg and the later measured
wipe each require separate confirmation. Old recorded paths cannot be executed.
A no-op home route has an explicit message. Server restarts clear an unavailable
remembered run in the browser.

## Photonics AI mascot

The composer includes the reusable `<photonics-mascot asset-base="/static/mascot/">`
custom element from `static/mascot.js`, styled by `static/mascot.css`. Its five
transparent 256 px assets live in `static/mascot/`. Only the current behavior is
fetched; subsequent triggers reuse its downloaded data with a new blob URL to
restart the GIF. No animation library is required.

Idle is the default. Hover or keyboard focus plays one wave, and click, tap,
Enter, or Space plays one hop and opens the Photonics assistant panel. The panel
accepts questions, tasks, and clarification replies through the same composer/API
as the main conversation. Shortcuts fill a draft; Send submits it. Drafts are
shared with the main composer, and responses appear in the conversation. An
active task blocks unrelated submissions; exact-path approval remains required.
Escape or the close button dismisses the panel and returns keyboard focus.

Demo mode can answer lab-status questions using simulated printer state and
synthetic board data. Unsupported questions/text are rejected rather than
becoming cleaning requests. For model-based lab requests, configure `GROQ_API_KEY`
locally in `.env` and launch `.venv/bin/python app.py --printer-mode mock` without
`--demo`; the printer remains simulated. Never paste the key into chat. This
panel does not add general web browsing, arbitrary computer control, or a separate
general-purpose model endpoint.

`ui.js` sets the component's `processing` property
from actual request/workflow activity; this selects scanning until activity ends.
Gestures return to scanning while processing, otherwise idle. The separate
pause/resume button persists the user's choice. Reduced-motion preferences and
hidden tabs use the static poster. Disconnecting the element clears timers,
listeners, pending fetches, and object URLs.

Adjust `--mascot-size` in `static/mascot.css` (64 px desktop, 48 px at the 800 px
breakpoint), `--mascot-inset` for the starting distance from the composer's right
edge, and `--mascot-travel` for how far it wanders along the top border. The asset's
transparent bottom margin is accounted for so its visible feet meet that border.
Hover, focus, processing, pause, and reduced motion stop the wandering. The compact
pause control sits above the border too; typing and send controls remain clear.
The component inherits the existing light/dark theme and bilingual labels.

Browser verification: `node --test tests/ui_integration.cjs tests/lan_browser.cjs`
with Playwright and its Chromium browser available. Mascot checks use mock APIs,
cover motion/pause/keyboard behavior and real workflow state wiring, and save
light/dark desktop/mobile examples under `results/ui-review/mascot-*.png`.
