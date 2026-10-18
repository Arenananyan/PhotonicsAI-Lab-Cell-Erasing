# Printer JSON interface, version 1

Use the same request object with either:

- **MCP:** call `printer_command(request=COMMAND_OBJECT)`.
- **Terminal:** start `./printerctl json --mock`, send one JSON object per input
  line, and read one JSON response per output line. Keep the process open to poll
  jobs. `./printerctl json --real` uses the existing shared authenticated SSH
  session, `SSH_HOST` and `SSH_CONTROL_PATH`.

The JSON runner defaults to simulation. Real movement additionally requires
`PRINTER_ALLOW_MOTION=1` in the process environment. This local gate does not
replace operator approval of each previewed physical path. No code in this
interface sets that flag automatically.

## Units and limits

Targets are **absolute X/Y/Z positions in millimetres**, relative to the configured
machine origin. All three coordinates are required. `speed_mm_s` is the straight
path speed in **millimetres per second**, defaults to **20**, and can be increased
to **30**. Both the original and 0.001 mm rounded target are validated.

Travel bounds come from the firmware's `toolhead.axis_minimum` and `axis_maximum`.
`capabilities`, `status` and `position` expose `data.travel_limits_mm` as
`{"x":[minimum,maximum],"y":[minimum,maximum],"z":[minimum,maximum]}` and
`data.travel_limits_source:"firmware"`; movement previews expose `data.plan.limits_mm`.
There are no guessed bounds if firmware limits are unavailable or invalid.
Start and target, including rounded coordinates, must fit these limits. Negative
coordinates are valid within them. Bounds are rechecked before dispatch and during
execution; a change since preview rejects execution with `PREVIEW_CHANGED`.
All three axes must be homed before
absolute movement. The printer must be idle/stationary, with zero heater targets,
100% speed override, zero coordinate offsets and inactive bed mesh. Mesh changes
stay explicit Terminal actions; the LLM interface cannot clear/load mesh.

The on-printer configuration is read for global/Z velocity and acceleration caps.
Requested speeds are rejected if unsupported. Without verified firmware caps,
speeds above 20 are rejected. Defaults stay at 20. Firmware acceleration remains
in control; no acceleration, velocity-limit or calibration setting is rewritten.
`capabilities` returns these limits and their units.

## Move workflow

Preview (the `preview` field defaults to `true`):

```json
{"id":"preview-1","command":"move","target":{"x":100,"y":120,"z":30},"speed_mm_s":25,"preview":true}
```

The response has `status: "previewed"`. `data.token` is valid for 120 seconds and
can be used once. `data.plan` contains start, requested and rounded targets,
speed, straight-line path and nominal duration. Acceleration can add time.

After the operator reviews and approves physical clearance, repeat the original
target and execute the token:

```json
{"id":"move-1","command":"move","target":{"x":100,"y":120,"z":30},"speed_mm_s":25,"preview":false,"token":"TOKEN_FROM_PREVIEW","operator_confirmed":true}
```

The response is `accepted` with `data.job_id`. Acceptance does **not** mean motion
completed. Poll the job until `completed`, `error`, or `stopped`:

```json
{"id":"poll-1","command":"job","job_id":"JOB_ID_FROM_EXECUTION"}
```

Omitting speed on execution inherits the token's preview speed. Supplying a
different target or speed requires a new preview. Dispatch reconstructs the plan
and rechecks the starting position. Uncertain outcomes are never retried.

## Read and stop commands

```json
{"command":"position"}
{"command":"status"}
{"command":"capabilities"}
{"command":"stop"}
```

`position` returns `data.position_mm`, `homed_axes`, `busy`, `active_job_id`, and
`firmware_state`. `status` adds the firmware state objects. Read and stop commands
remain available while an operation is running. Additional move/home commands
are rejected with `BUSY`; they are never queued. If another Terminal process owns
the on-printer lock, its operation also prevents dispatch.

`stop` requests **emergency shutdown**, not pause/resume or a controlled decelerating
stop. Confirmation is reported; failed delivery is `STOP_UNCONFIRMED` or a connection
error. Stop invalidates previews. Manual inspection/recovery is required before
new movement. A currently running job can report `stopped` with an error explaining
the interruption. Request IDs correlate replies; they are not idempotency keys.

## Homing

```json
{"command":"home","axes":["x","y","z"],"preview":true}
```

Homing axes default to all three. To execute, repeat axes with `preview:false`,
the returned token, and `operator_confirmed:true`; poll the returned job ID.
Homing runs in simulation. Real homing defaults to **manual** and returns
`HOME_CONFIGURATION_REQUIRED`: use the touchscreen and check `status` afterward.

The optional local `PRINTER_HOMING_MODE=firmware` configuration exposes the
inspected Ender-3 V3 KE firmware routine, still behind the motion flag and per-run
confirmation. Choose this mode only after reviewing that routine: it can move
axes to firmware endstops, lift unhomed Z by
5 mm, move X/Y at 80–100 mm/s, and save/clear/reload bed mesh. The 30 mm/s ordinary
movement cap does not replace firmware homing speeds. No heating/extrusion
commands were found in the inspected macros.

The backend rejects a changed homing configuration fingerprint or Z-lift variable,
revalidates the preview state before dispatch, and monitors telemetry, firmware
travel bounds, heaters and extrusion during homing. Homing invalidates existing
previews. It can leave a negative homing position or active mesh, so it does not
certify readiness for a later absolute movement; obtain a fresh status/preview.

## Response format

Every command returns the same envelope:

```json
{"version":1,"id":"preview-1","command":"move","ok":true,"simulated":true,"status":"previewed","message":"Review the path before confirming execution","data":{"token":"...","expires_in_seconds":120,"plan":{}},"error":null}
```

Errors use `ok:false`, a status and a structured `error` object:

```json
{"version":1,"id":"move-1","command":"move","ok":false,"simulated":true,"status":"error","message":"Another motion or homing operation is active; command was not queued","data":null,"error":{"code":"BUSY","message":"Another motion or homing operation is active; command was not queued","retryable":false,"details":{}}}
```

Common codes: `INVALID_JSON`, `INVALID_COMMAND`, `INVALID_ARGUMENT`, `OUT_OF_BOUNDS`,
`NOT_HOMED`, `BUSY`, `MESH_ACTIVE`, `HEATING_ACTIVE`, `MOTION_DISABLED`,
`CONFIRMATION_REQUIRED`, `TOKEN_INVALID`, `PREVIEW_CHANGED`, `JOB_NOT_FOUND`,
`HOME_CONFIGURATION_REQUIRED`, `STOP_UNCONFIRMED`, `CONNECTION_ERROR`, and
`OUTCOME_UNCERTAIN`. Details can report whether a command might have executed and
whether an emergency stop was confirmed. Do not infer physical safety from position
estimates, acceptance, an error, or a stop request alone.

Watchdog failures can include `error.details.diagnostics`: initial/target positions,
the startup-window limit, recent queued/live positions and velocities, and query
timings. Preserve these when asking the operator to investigate. The exact
0.5-second startup policy remains enforced; diagnostics do not authorize retrying.

Only the documented fields are accepted. Unknown fields, booleans as coordinates
or speeds, non-finite numbers and duplicate JSON keys are rejected. Heating,
extrusion, raw G-code and coordinate resets are not part of this interface.

See [JSON schema](printer-interface.schema.json) and the short
[LLM instruction text](LLM_PROMPT.md). Automated validation uses mock printers,
local Unix sockets, the JSON runner and MCP clients; no new physical movement or
homing was tested.
