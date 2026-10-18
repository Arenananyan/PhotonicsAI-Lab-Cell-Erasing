# Photonics Printer MCP

Move a 3D printer from Python steps, a Terminal command, or a FastMCP client.
Sequences are queued together to avoid a pause between every short movement.
An on-printer watchdog checks firmware position reports and requests an emergency
stop when a check fails.

**Tested hardware:** Creality Ender-3 V3 KE, firmware V1.1.0.17, root SSH enabled.
The host was macOS with Python 3.14.7; the printer runs Python 3.8.2. This is a
controller for that setup, not a universal driver for any 3D printer. Another
model needs a review of its SSH access, Klipper API, coordinates and limits first.

> Real commands move machinery. Stay beside the printer, verify the entire path
> is clear, and keep other printer controls idle during a run. The watchdog uses
> firmware estimates; it cannot detect every collision or guarantee a stop before
> a physical boundary. See [safeguards and limitations](#safeguards-and-limitations).

## 1. Install and simulate first

Run these commands on your **Mac**, not inside the printer's SSH shell:

```bash
git clone https://github.com/WhoEvenAm/photonics-printer-mcp.git
cd photonics-printer-mcp
python3 --version                       # Python 3.10 or newer
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./printerctl --mock
```

The terminal runner uses the Python standard library. `requirements.txt` installs
FastMCP 4.1.0 for the MCP server and full test suite. `requirements.lock.txt` records
the dependencies from the original tested macOS environment; use it when reproducing
that environment, rather than assuming its platform-specific packages fit every OS.

`--mock` is simulation and makes no SSH connection. **Without `--mock`, terminal
commands target hardware.** The MCP server, separately, defaults to simulation.

`simple.py` holds your editable sequence of relative steps. The current local
sequence moves **Y +50 mm at 20 mm/s**. Absolute targets use the separate `move`
command below and do not run those steps.

## 2. Connect to your printer

The printer must be reachable from the Mac on the local network and have root
SSH access enabled through its own settings. Find its current IP on its screen.
No printer address or password is bundled with the code.

Create a local configuration:

```bash
cp .env.example .env
open -e .env
```

Replace the example address with **your printer's IP**. The file contains shell
`export` statements. It is ignored by Git and is **not loaded automatically**.
Do not put passwords in it.

In **Terminal tab 1**:

```bash
cd /path/to/photonics-printer-mcp
source .env
./printerctl connect
```

Verify the SSH host fingerprint when first connecting. Enter the root password
locally; password characters are hidden. After login the tab stays open and idle.
This is expected: the command opens a shared SSH session with `ssh -N`. Leave it
open. If it exits or the printer restarts, reconnect.

In **Terminal tab 2**:

```bash
cd /path/to/photonics-printer-mcp
source .env
./printerctl status
```

Both tabs must use the same `SSH_HOST` and `SSH_CONTROL_PATH`. Alternatively,
export those variables directly in both tabs. The default control socket is
`/tmp/photonics-printer-control`; give each printer a distinct socket if using
more than one. Physical movement still requires a preview and confirmation.

## 3. Make your first movement

Home the required axes using the printer controls. X/Y-only steps require X and
Y homed; any Z step requires all three axes homed. Moving an axis by hand does
not establish firmware homing. The runner does not perform homing.

For a short X test:

```bash
./printerctl test-move
```

This previews **X +5 mm and back**, normally at 20 mm/s. If mesh compensation is
active, it first offers to unload it: type `CLEAR` only after reviewing that action.
Saved calibration is retained. It then prints the checked movement plan; type
`MOVE` to execute. Any other response cancels that action. A slower visible test:

```bash
./printerctl test-move --speed 5
```

The full requested path must fit the bounds, including the starting position.
For example, the +5 mm test requires starting X at least 5 mm below the reported
X maximum (216 mm with the currently reported maximum of 221 mm).

For your steps in `simple.py`:

```bash
./printerctl --mock       # simulate
./printerctl --preview    # read hardware state and validate; never moves or clears mesh
./printerctl              # prepare, show the plan, then ask for MOVE
```

If a preview reports active mesh, use `./printerctl mesh-clear`, type `CLEAR`,
and preview again. Normal execution can offer that same separate confirmation.
After movement testing, restore the saved mesh before printing:

```bash
./printerctl mesh-load default
```

Type `LOAD`. Use your actual profile name if it differs from `default`.

## Move to an absolute XYZ position

Enter **X, Y, Z in that order, in millimetres**, relative to the printer's configured
machine origin. For example, to target X=100, Y=120, Z=30 at 5 mm/s:

```bash
./printerctl move 100 120 30 --speed 5 --mock     # simulation
./printerctl move 100 120 30 --speed 5 --preview  # read-only hardware preview
./printerctl move 100 120 30 --speed 5            # preview, then type MOVE
```

The path is one **straight line from the current XYZ position to the target**;
it does not lift Z first or avoid obstacles. Review the displayed path and physical
clearance before confirming `MOVE`. Status changes from preview to moving to
completed, with the final reported position; errors are printed as `Stopped:`.
If already at the target, it sends no movement.

All three axes must be firmware-homed using the printer controls, even if Z is
unchanged. Both the start and target must lie within the **reported firmware travel
limits**, including valid negative coordinates. The latest read returned X -12..221,
Y -20..223 and Z -5..246 mm; each preview reads fresh limits rather than assuming
those values. Invalid or non-finite coordinates and
speeds are rejected. Targets are rounded to 0.001 mm after validating the requested
values. The configured origin is never relabelled; nonzero coordinate offsets
remain unsupported.

`--speed` sets the whole movement's speed, normally 20 mm/s, limited by both the
existing X/Y and Z software caps (currently 30 mm/s) and verified firmware
velocity limits. `--z-speed` is only for relative step sequences.
The preview reports nominal duration; acceleration can add time.

The printer must be idle and stationary, heater targets must be zero, and mesh
compensation must be inactive. Absolute movement never clears mesh implicitly:
use `./printerctl mesh-clear`, review and confirm `CLEAR`, then preview again.
Starting outside the reported firmware bounds must be resolved with the printer controls
before using this command. Movement contains no heating, extrusion, homing or
firmware-limit changes. Remote dispatch rechecks homing, position, limits and
speed after confirmation; the existing watchdog and emergency stop stay active.

## 4. Write your own steps

Open `simple.py` in an editor:

```bash
open -e simple.py
```

`fw(axis, distance)` increases an axis coordinate. `bc(axis, distance)` decreases
it. Distances are positive **millimetres**; 50 mm is 5 cm. These functions build
step dictionaries, and `run(...)` executes them in order. Merely importing the
file or writing a standalone `fw(...)` expression does not move the printer.
On the Ender-3 V3 KE, Y movement moves the bed; increasing Z raises the gantry.

### A 50 × 50 mm square

```python
from simple_runner import fw, bc, x, y, z, run

SPEED = 20.0        # X/Y mm/s; maximum 30, further capped by firmware
Z_SPEED = 20.0     # Z mm/s; maximum 30, further capped by firmware
STEPS = [
    fw(x, 50),
    fw(y, 50),
    bc(x, 50),
    bc(y, 50),
]

if __name__ == '__main__':
    raise SystemExit(run(STEPS, SPEED, z_speed=Z_SPEED))
```

This direction of square needs starting X and Y at least 50 mm below their reported
maximums, while remaining above their minimums. With the latest limits, that is
X -12..171 and Y -20..173 mm. It returns to
its start. At 20 mm/s each 50 mm side takes about 2.5 seconds plus acceleration
and cornering time. This traces motion only: it does not extrude or print a line.

### Raise Z by 10 mm

Replace only the `STEPS` list with:

```python
STEPS = [fw(z, 10)]
```

This adds 10 mm to the current Z; it does **not** set Z to 10. At the default
20 mm/s it takes about 0.5 seconds plus acceleration. For a raise and return:

```python
STEPS = [fw(z, 10), bc(z, 10)]
```

Check the lowering path as well as the raising path. Z must stay within its reported
firmware limits (currently -5..246 mm). For a 50 mm raise, use `fw(z, 50)` and start
at least 50 mm below the reported maximum (currently no greater than 196 mm).

### Separate movement files

You can keep the square and add another file, for example `raise_z.py`:

```python
from simple_runner import fw, z, run

if __name__ == '__main__':
    raise SystemExit(run([fw(z, 10)], z_speed=2))
```

Run it on the Mac with the same connection variables:

```bash
.venv/bin/python raise_z.py --mock
.venv/bin/python raise_z.py --preview
.venv/bin/python raise_z.py
```

`printerctl` always runs `simple.py`; call your separate file with Python.

## Terminal command reference

| Command | Effect |
| --- | --- |
| `./printerctl connect` | Open the shared SSH session; leave this tab open. |
| `./printerctl status` | Read printer state, homed axes, mesh, temperatures and positions. |
| `./printerctl --mock` | Simulate the steps in `simple.py`; no hardware access. |
| `./printerctl --preview` | Read and validate the full sequence without changing printer state. |
| `./printerctl move X Y Z --speed 5 --preview` | Preview one straight move to absolute XYZ millimetres. |
| `./printerctl move X Y Z --speed 5` | Preview and confirm MOVE to that absolute target. |
| `./printerctl json --mock` | Persistent JSON-lines interface for LLM commands in simulation. |
| `./printerctl json --real` | JSON-lines interface over the shared SSH session; real motion stays locally gated. |
| `./printerctl` | Prepare and execute `simple.py` after confirmations. |
| `./printerctl test-move` | Preview and confirm X +5 mm and return. |
| `./printerctl --speed 5` | Run `simple.py` with X/Y limited to 5 mm/s. |
| `./printerctl --z-speed 1` | Run `simple.py` with Z at 1 mm/s; X/Y speed is unchanged. |
| `./printerctl mesh-clear` | Type `CLEAR` to unload compensation; saved calibration remains. |
| `./printerctl mesh-load default` | Type `LOAD` to load the named saved mesh. |
| `./printerctl xy-start-preview` | Preview the special entry from the known negative homing area. |
| `./printerctl xy-start` | Type `ENTER` to approve that entry move; see below. |
| `./printerctl stop` | Request emergency shutdown; manual recovery is required. |

Speed options combine with `--mock` or `--preview`. Action options such as
`--preview`, `--status`, and `--test-move` are mutually exclusive.

### When `xy-start` is useful

This tested printer has reported X=-12, Y=-15 after X/Y homing. Regular sequences
now accept negative coordinates within reported firmware limits, so this helper
is optional. `xy-start` is a separate, confirmed straight
move to X=0, Y=0 at 5 mm/s, with no Z command. It accepts only starting X in -12..0
and Y in -15..0. During entry, the watchdog checks the displayed rectangle from
that start to zero. This is a specific tested setup, not a generic homing routine.

If already inside the nonnegative portion of the reported X/Y travel limits,
it explains that entry is unnecessary and sends no
move. It does not certify readiness for the next sequence. With Z unhomed or
reported as zero, physical nozzle clearance must be checked by the operator.
It never resets coordinates and never homes an axis.

## Troubleshooting

| Message or symptom | What to check |
| --- | --- |
| `Set SSH_HOST...` | Run `source .env` in this tab, with your printer's current IP. |
| `No route to host` / connection timeout | Printer power, its displayed IP, and local network reachability. |
| `Shared SSH session unavailable` / SSH 255 | Reopen `./printerctl connect` in tab 1; check its error output. |
| `./printerctl: no such file` | Change into the cloned folder first. |
| `.venv/bin/python: not found` at a `root@...` prompt | You are inside the printer shell. Use a Mac Terminal tab and the cloned folder. |
| No password characters or success message | SSH hides password entry; an idle connected tab is normal with `-N`. |
| `Home ... axes` | Use printer homing controls; hand-positioning is insufficient. |
| `outside allowed travel bounds` / `outside firmware travel bounds` | Read status and check the whole path against its reported axis minimums and maximums. Negative coordinates inside those limits are valid. |
| Toolhead/G-code positions disagree | Check mesh state. Unload it explicitly for testing, then re-preview; do not relabel coordinates with G92. |
| `Unexpected Z change`, stop requested, or screen error 2001 | Inspect the printer and preserve the terminal error. Do not automatically retry. An emergency stop can require manual restart and homing. |
| `No confirmed live position within the 0.5-second startup window` | The watchdog requested shutdown because live telemetry did not recover in time. Preserve the error and its diagnostics; inspect and recover the printer manually before a fresh preview. Reported queued target coordinates do not prove completion. |
| Terminal shows `quote>` | Press Ctrl-C to cancel the unfinished quote; paste commands without an extra leading apostrophe. |
| `Another simplified runner is already active` | Let the other run finish; do not bypass the lock. Emergency stop uses a separate path. |

The original error 2001 incident followed our watchdog's emergency-stop request
for `Unexpected Z change`. It is not evidence that every error 2001 has that cause.

## Safeguards and limitations

At the operator's request, travel bounds now come from the printer's reported
`toolhead.axis_minimum` and `axis_maximum`, through one shared policy function.
The latest read returned **X -12..221 mm**, **Y -20..223 mm**, **Z -5..246 mm**.
Missing or invalid firmware bounds reject movement; there is no guessed fallback.
Bounds are read at preview, checked again before dispatch, and monitored during
execution. Changed bounds require a fresh preview. These coordinates do not certify
physical clearance. Firmware limits are never rewritten.

The operator-approved speed limits remain **X/Y ≤30 mm/s** and **Z ≤30 mm/s**,
with defaults of 20 mm/s, further restricted by verified firmware limits.

On October 14, 2026, the operator requested faster adjustable movement for LLM
control after setting the Z default to 20 and reporting a 30 mm/s maximum.
Read-only firmware configuration confirmed global velocity 500 mm/s, Z velocity
30 mm/s, global acceleration 8000 mm/s² and Z acceleration 300 mm/s². Software
keeps the more conservative 30 mm/s ceiling, intersects firmware velocity limits,
and rejects current acceleration exceeding the configured cap. Acceleration
continues under firmware control; no settings are rewritten. Speeds above 20
require verified firmware motion settings. Historical physical Z tests below
used 2 mm/s; faster speeds and the new homing interface have simulation evidence only.

The runner validates the complete path, including rounded command coordinates,
before dispatch. It rechecks the starting position immediately before sending one
queued script (`G90`, movement commands, `M400`). The watchdog runs beside Klipper
on the printer and checks live and queued position, homing, idle state, heater
targets, speed override, offsets, timestamps, velocity and final completion.
It requests an emergency stop on execution faults, stale/missing telemetry or a
deadline failure. It does not automatically retry uncertain motion.

Firmware configuration limits are read at preflight and cached for each operation.
Fast telemetry polls omit the full configuration while continuing to read all
motion guards and dynamic toolhead limits. Fault replies include bounded recent
telemetry and query timings. Those diagnostics assist investigation; they do not
prove the cause of a firmware zero report or physical movement completion.

Important limits of that protection:

- It observes firmware estimates, not independent physical sensors. Skipped steps,
  collisions and controller failure may not be detected correctly.
- Polling is approximately 100 ms; firmware position refresh may be about 250 ms.
  A normal missing-response timeout is 1 second. A boundary can be crossed before
  detection and shutdown. Keep physical clearance beyond the planned path.
- A documented firmware quirk may report exact live XYZ `[0,0,0]` and velocity
  zero briefly after dispatch. The approved exception allows at most **0.5 seconds**
  for valid live telemetry to arrive. Fixed/planned Z checks for that missing sample
  are deferred; other checks continue. The window closes on the first nonzero
  position/velocity report and cannot reopen. Preflight/final checks stay strict.
  Movement is possible during that uncertain interval: up to 15 mm at 30 mm/s,
  plus physical stopping latency. The watchdog stops if the window expires.
- Status bounds allow only 1e-9 arithmetic roundoff; command targets remain strict.
  The separate fixed/planned Z comparison tolerance is 0.002 mm.
- Ctrl-C attempts a stop if execution is in progress, but queued moves can continue
  if communication fails. Keep access to the physical power cutoff. `stop` is an
  emergency shutdown, not a pause/resume feature.
- The runner's lock excludes other copies of this runner, not touchscreen commands
  or unrelated applications. Leave those idle during execution.
- Heating, extrusion, arbitrary G-code, coordinate resets and automatic homing are
  not exposed. There is no global skew-compensation detection; don't treat these
  checks as validation of every possible custom firmware transform.

## FastMCP / AI clients

For an LLM integration, use the consistent version 1 JSON interface through
`printer_command(request=...)` or `./printerctl json --mock`. It exposes absolute
movement with optional speed, homing, position, status, capabilities, emergency
stop and operation polling. Move/home previews issue single-use 120-second tokens;
execution requires operator confirmation. Operations run asynchronously and
return job IDs; additional movement is rejected as busy, never queued. Position,
status and stop remain available. Heating, extrusion and raw G-code are excluded.

See the [interface and examples](docs/LLM_INTERFACE.md),
[JSON schema](docs/printer-interface.schema.json), and short
[instruction text to give the LLM](docs/LLM_PROMPT.md).

Real homing defaults to the touchscreen. The optional local
`PRINTER_HOMING_MODE=firmware` setting exposes the inspected homing routine, after
preview and approval: it includes a 5 mm pre-homing Z lift, X/Y moves at
80–100 mm/s, and mesh changes. Its speeds are controlled by firmware, separately
from the ordinary movement ceiling. The homing configuration fingerprint and
live Z-lift variable are checked before dispatch. This interface never enables
real motion or firmware homing automatically. All new physical actions remain
untested; automated tests use simulations.

Klipper documents [homing and movement commands](https://www.klipper3d.org/G-Codes.html#g-code-commands)
and [firmware motion limits](https://www.klipper3d.org/Config_Reference.html#common-kinematic-settings).

Start the stdio server in simulation:

```bash
.venv/bin/python fastmcp_server.py
```

| Tool | Behavior |
| --- | --- |
| `printer_status()` | Read state. |
| `printer_command(request)` | Consistent JSON interface for movement, home, status, position, capabilities, stop and asynchronous job polling. |
| `preview_sequence(steps, speed_mm_s=20, z_speed_mm_s=20)` | Validate a sequence and return a token valid for 120 seconds. |
| `preview_position(x, y, z, speed_mm_s=20)` | Validate one straight absolute XYZ movement; all axes must be homed; return a 120-second token. |
| `execute_sequence(token, operator_confirmed=False)` | Execute a reviewed sequence or absolute movement once after operator confirmation. |
| `emergency_stop()` | Request shutdown independently of the sequence lock. |

Example step dictionaries:

```json
[{"axis": "z", "distance_mm": 10}, {"axis": "z", "distance_mm": -10}]
```

For an absolute target, call `preview_position` with
`{"x": 100, "y": 120, "z": 30, "speed_mm_s": 5}`. Use its token with
`execute_sequence` only after the operator approves the displayed straight path.
The same real-motion gate, expiry, single-use tokens and no-retry behavior apply.

To configure an MCP client, use the absolute path to `.venv/bin/python` as its
command and the absolute path to `fastmcp_server.py` as its argument. Set environment
variables explicitly in that client; it does not inherit another Terminal tab's
exports automatically. `PRINTER_MODE=mock` is the default. Real status/preview access
requires `PRINTER_MODE=real`, `SSH_HOST`, and the shared SSH session. Real execution
also requires the operator to set `PRINTER_ALLOW_MOTION=1`; that flag alone does not
replace approval of each reviewed path. Pass `operator_confirmed=true` only after
that approval. Mesh management and `xy-start` remain terminal-only operations.

The requested “FastMCP dictionaries” are Python dictionary steps and dictionary
tool results through the FastMCP library. No separate FastMLP component is used.

## Development and test evidence

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

Tests use mock printers, local Unix sockets, stubbed SSH transport, and in-process
and stdio FastMCP clients. They do not contact a physical printer. The included
GitHub Actions workflow runs this suite on Linux and macOS.

On October 13, 2026, the original controller reported successful hardware tests:

| Test | Result and evidence |
| --- | --- |
| X +5 mm and return at 20 mm/s | Firmware confirmed completion; operator did not see the brief motion. |
| X 120 → 150 → 120 mm at 5 mm/s | Firmware confirmed completion; a mid-run report showed motion, and the operator confirmed seeing it. |
| Z 5 → 15 mm at 2 mm/s | Watchdog confirmed final Z=15; X/Y stayed at 110. |
| Z 15 → 65 mm at 2 mm/s | Watchdog confirmed final Z=65; X/Y stayed at 110. |

These are historical test coordinates, not the current position or a startup
assumption. The sharing copy changes host configuration and test portability;
its movement policy is retained. For the detailed architecture and AI continuation
notes, read [package validation](../docs/VALIDATION.md) and [AGENTS.md](AGENTS.md).

## License

[MIT](LICENSE). No passwords, private SSH keys, personal printer IP, local virtual
environment or diagnostic logs are included.

## Coupled XY sequence legs

`preview_sequence` also accepts `{"axis":"xy","distance_mm":[dx,dy]}`.
This is one straight simultaneous XY G1 move at the sequence XY speed; it never
changes Z. Scalar x/y/z legs remain compatible. Both requested and rounded
endpoints, firmware bounds, offsets, homing, heaters, dispatch revalidation,
watchdog telemetry and single-use approvals still apply. The lab agent builds
a clockwise circle from 72 such legs, all previewed as one sequence.
