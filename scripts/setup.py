#!/usr/bin/env python3
"""Install isolated component environments; never connect to hardware."""
import argparse
from pathlib import Path
import subprocess
import sys
import venv

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-iphone',action='store_true')
    args=parser.parse_args()
    if sys.version_info < (3,11):
        parser.error('Use Python 3.11 or newer.')
    components=['lab-agents','shape-scanner','photonics-printer-mcp-main']
    if args.with_iphone:components.append('camera-control')
    for component in components:
        directory=ROOT/component
        environment=directory/'.venv'
        if not environment.exists():venv.EnvBuilder(with_pip=True).create(environment)
        python=environment/'bin/python'
        subprocess.run([str(python),'-m','pip','install','-r',str(directory/'requirements.txt')],check=True)
        subprocess.run([str(python),'-m','pip','check'],check=True)
    (ROOT/'shape-scanner/results/images').mkdir(parents=True,exist_ok=True)
    (ROOT/'lab-agents/results').mkdir(parents=True,exist_ok=True)
    print('Setup complete. No hardware connection or movement was requested.')

if __name__=='__main__':main()
