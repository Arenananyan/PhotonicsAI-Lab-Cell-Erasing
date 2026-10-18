#!/usr/bin/env python3
"""Run offline component suites; no real printer or camera is contacted."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
(ROOT/'shape-scanner/results/images').mkdir(parents=True,exist_ok=True)
for name in ('photonics-printer-mcp-main','shape-scanner','lab-agents'):
    directory=ROOT/name
    python=directory/'.venv/bin/python'
    if not python.exists():raise SystemExit('Run python3 scripts/setup.py first.')
    subprocess.run([str(python),'-m','unittest','discover','-s','tests','-v'],cwd=directory,check=True)
