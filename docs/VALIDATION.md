# Package validation — 18 October 2026

The checks below ran against the copied source in this package. Existing local
Python environments were temporarily linked for testing, then the links were
removed. Virtual environments are not submission artifacts. A completely fresh
network installation has not been run; use scripts/setup.py to install from the
component requirements files.

| Component | Result | Scope |
| --- | --- | --- |
| Printer | 143 passed | Mock state, local socket, schemas, MCP and motion-policy validation |
| Scanner | 61 passed | Synthetic images, calibration, detection, camera-source API and MCP |
| Lab agents | 104 passed | Workflows, batches, spatial selection, clarification, evidence and access |
| Browser | 29 passed | Mocked APIs, mobile/desktop, themes, chat, images and path approval |
| Optional iPhone adapter | 4 passed | Viewport rendering/control tests with a synthetic JPEG |

The Python source was syntax-checked. Browser tests rendered screenshots and passed
layout checks; screenshots are temporary review artifacts, not recorded hardware
results. The copied component paths remained intact during tests.

No real SSH connection, firmware reset, homing, heating, mesh modification or
physical movement was performed as part of package preparation. No live Groq
request was sent. These tests do not demonstrate physical ink removal or available
provider quota. A live presentation still requires operator checks, current camera
calibration and successful model access.

## Preserved behavior

- Two independent MCP clients: scanner and printer.
- Fresh calibrated stationary observations and 3 mm association tolerance.
- Host-computed center-to-center XY distances, validated LLM proposals.
- Separate numbered choice for near-equal largest/smallest cells.
- Same-frame board/cell pictures served with path and frame validation.
- Explicit path approval and single-use dispatch tokens.
- One attempt per initial batch target, with final residue/uncertainty reporting.
- No automatic motion retry after an uncertain transport outcome.
- Groq quota errors include provider detail and Retry-After when supplied.

## Packaging changes

- Preserved source, component interfaces, tests, UI assets and printer license.
- Excluded virtual environments, Git metadata, logs, screenshots, run histories,
  captured camera images, machine calibration, credentials and local editor files.
- Replaced machine-specific documentation paths and old assignment .env references.
- Optional iPhone examples default to loopback; pass the phone address explicitly.
- Added root installation guide, environment setup, offline check script,
  videos directory and a placeholder for the later report.

Two operator-supplied recordings, IMG_0030.MOV and IMG_7455.MOV, were added after
these checks. They are supplementary material; these test results do not validate
their contents. The final PDF report is pending.
