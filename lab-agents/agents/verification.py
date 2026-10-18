"""Bounded local evidence worker; no camera or printer commands."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4


async def compare(before,after,target,directory):
    root=Path(__file__).resolve().parents[2]
    output=Path(directory)/'evidence'/uuid4().hex
    proc=await asyncio.create_subprocess_exec(str(root/'shape-scanner/.venv/bin/python'),
        str(Path(__file__).with_name('evidence.py')),stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        stdout,stderr=await asyncio.wait_for(proc.communicate(json.dumps(dict(before=before,after=after,target=target,output=str(output))).encode()),20)
    except BaseException:
        proc.kill();await proc.wait();raise
    result=json.loads(stdout)
    if proc.returncode or result.get('error'): raise ValueError(result.get('error','Evidence worker failed'))
    return result
