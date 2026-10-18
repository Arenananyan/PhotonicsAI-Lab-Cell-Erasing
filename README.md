# PhotonicsAI Lab — Agentic Cell Erasing

**From Prototype to Product**

A browser application for inspecting colored cells, asking measured spatial questions,
and preparing operator-approved printer paths. The submitted product combines the
chat dashboard, calibrated camera scanner and bounded printer MCP interface.

**Team:** Aren Ananyan · David Sargsyan · Andranik Arakelyan · Yerem Bareghamyan

## What is included

| Folder | Purpose |
| --- | --- |
| `lab-agents/` | Armenian/English chat, Groq proposals, host validation and UI |
| `shape-scanner/` | Color detection, board calibration, saved frames and scanner MCP |
| `photonics-printer-mcp-main/` | SSH/Klipper interface, motion validation and mock printer |
| `camera-control/` | Optional Blackmagic iPhone adapter; Android does not need it |
| `presentation/` | Supplied 10-slide presentation PDF |
| `screenshots/` | Website UI screenshots (offline demonstration data) |
| `videos/` | Two supplied hardware recordings |
| `docs/` | Validation notes and editable LaTeX report sources |
| `scripts/` | Environment setup and offline checks |

The components stay as siblings: image workers and MCP startup use these relative
locations. No old repository, API key, SSH password, camera calibration, run history
or virtual environment is included. The original working project is untouched.

## Install

Use macOS/Linux and Python 3.11 or newer with pip/venv, then run from this folder:

```sh
python3 scripts/setup.py
cp lab-agents/.env.example lab-agents/.env
```

Set `GROQ_API_KEY` locally in `lab-agents/.env` for live language requests.
Do not commit this file. The setup installs dependencies and creates output folders;
it never starts devices or sends motion. To also install the optional iPhone adapter,
use `python3 scripts/setup.py --with-iphone`.

## Hardware-free demonstration

In one terminal:

```sh
cd shape-scanner
.venv/bin/python run_cells.py --demo
```

In another terminal, from the repository root:

```sh
cd lab-agents
.venv/bin/python app.py --demo --printer-mode mock --env-file .env --port 8770
```

Open http://127.0.0.1:8770. Both the scripted language decisions and printer are
simulated; this mode demonstrates workflow/UI, not live LLM understanding or real
cleaning. For live Groq with a mock printer, omit `--demo`; the scanner must supply
valid evidence for actions that need it.

## Real hardware (operator-run)

1. Start the camera. Android IP Webcam is read locally at `http://127.0.0.1:8080/shot.jpg`;
   arrange the phone-to-computer connection so that this URL responds. iPhone is
   optional: see `camera-control/README.md` and pass its current address explicitly.
2. Start the scanner:

   ```sh
   cd shape-scanner
   .venv/bin/python run_cells.py --camera-source ip_webcam
   ```

   Open http://127.0.0.1:8767 and calibrate the actual board for this camera. This
   clean package deliberately does not reuse another machine's calibration.
3. In a separate terminal, establish SSH and leave it open:

   ```sh
   cd photonics-printer-mcp-main
   export SSH_HOST="YOUR_PRINTER_IP"
   export SSH_CONTROL_PATH="/tmp/photonics-printer-control"
   ./printerctl connect
   ```

4. In another terminal, verify the same host/socket with `./printerctl status`.
   Ready state, homing, coordinate agreement and mesh policy must pass. This package
   never resets firmware, homes, or changes mesh automatically.
5. Start the dashboard from `lab-agents/` with real motion disabled initially:

   ```sh
   export SSH_HOST="YOUR_PRINTER_IP"
   export SSH_CONTROL_PATH="/tmp/photonics-printer-control"
   export PRINTER_ALLOW_MOTION=0
   .venv/bin/python app.py --printer-mode real --env-file .env --port 8770
   ```

To enable operator-reviewed execution, restart the dashboard with
`PRINTER_ALLOW_MOTION=1`. Each path still requires the UI's explicit clearance
confirmation and approval. Startup itself does not move the printer. HOME is the
configured observation position (209, 208, 100 mm), distinct from firmware homing.

## Presentation commands

- `Քանի՞ կապույտ և քանի՞ կանաչ բջիջ կա։`
- `Ցույց տուր բջիջները մեծից փոքր՝ առանձին ըստ գույնի։`
- `Որքա՞ն է ամենամեծ կապույտ և ամենամեծ կանաչ բջիջների հեռավորությունը։`
- `Գտիր ամենամեծ կանաչ բջջին ամենամոտ կապույտ բջիջը։`
- `Մաքրիր ամենամեծ կանաչ բջջին ամենամոտ կապույտ բջիջը։`
- `Եթե կապույտ բջիջները 10-ից շատ են, մաքրիր ամենամեծ կանաչը։`
- `Մաքրիր բոլոր կապույտ բջիջները։`

Recognition uses color/image processing and calibrated geometry, not a trained
biological-cell classifier. The LLM proposes structured operations; the host
calculates distances, validates scope and controls dispatch. See `lab-agents/README.md`
for the execution contract and supported bounded relations.

Close largest/smallest areas (within 5%) produce numbered choices and available
same-frame crops. After choosing a number, the system re-observes the target and
requests path approval. All-target cleaning validates fixed paths for the initial
queue and attempts each target once. Residue is reported, not automatically retried.

## Remote browser

Add `--host 0.0.0.0` to the dashboard command. On the same trusted Wi-Fi, open
`http://COMPUTER_IP:8770` (not `0.0.0.0`). Remote username is `lab`; the generated
password is stored locally in `lab-agents/.remote-access-password`. Loopback access
remains local. Plain HTTP uses unencrypted Basic authentication; use only the lab
network, without public port forwarding. This is a local lab product, not a hardened
internet service.

## Checks and limitations

```sh
python3 scripts/check.py
```

These are offline mock/synthetic/local-socket checks; they do not validate physical
clearance or ink removal. Browser tests are in `lab-agents/tests/ui_integration.cjs`
and require Node.js, Playwright and Chromium (development-only dependencies).

Groq quotas can block even inspection questions: the current coordinator and answer
path depend on live model access. The UI reports provider details and Retry-After
when supplied. It does not automatically retry physical motion. A visual-assessor
failure preserves usable local evidence but reports uncertain cleaning. Failed or
stale camera evidence still stops/pauses the workflow.

Live hardware was used in the original project. The copied submission must be
validated against the present camera/board before a new live presentation. Two supplied video recordings are included in `videos/` as `IMG_0030.MOV` and
`IMG_7455.MOV`. Their filenames are preserved; no specific physical outcome is
claimed here without reviewing the footage. The [final team report](output/pdf/PhotonicsAI_Homework4_Report.pdf) documents the implementation, evidence and future directions.


## Future applications

This is a **supervised prototype**. Colored-mark erasing is its first demonstration
application. Its reusable loop is: understand a request → locate a target → measure
and select → propose a path → obtain operator approval → execute → inspect the result.
The same architecture could be adapted to other instruments and tools.

| Development direction | Possible application | What must be added and validated |
| --- | --- | --- |
| Biomedical laboratories | Select a specimen region; position a camera or measurement probe | Microscopy-specific recognition, finer positioning, sample-compatible tools and application-specific validation |
| PCB inspection and repair support | Locate a component or suspected defect, position a probe, or assist local cleaning | PCB-specific perception, calibrated tooling, electrical precautions and force/temperature control where relevant |
| Industrial inspection | Measure, mark or locally process a selected region | Material-specific sensing, tools, tolerances and validated result criteria |
| Education and research | Supervised experiments and new instrument workflows | MCP adapters, repeatable procedures and structured records |

These are proposed directions, not capabilities demonstrated by the current
submission. The colored marks are not biological cells; no clinical application
or actual PCB repair is claimed. The next work should quantify targeting error,
repeatability, tool contact and removal effectiveness in controlled trials.

## Report and presentation

- [Homework 4 team report (PDF)](output/pdf/PhotonicsAI_Homework4_Report.pdf)
- [Editable LaTeX source](docs/report/main.tex)
- [Supplied presentation](presentation/agentic_cell_erasing_simple.pdf)
- [Validation details](docs/VALIDATION.md)

The report includes all four team members, the implemented product extension,
UI screenshots, the scope of the 341 software checks, supplied recordings,
limitations and proposed applications. Rebuild the PDF with `sh docs/report/build.sh` (requires Tectonic).
