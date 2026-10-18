"""Build display-only image artifacts; no printer operations."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4


async def observation_gallery(scene,ranked,directory):
    if not (scene.get('frame') or {}).get('raw_image'):raise ValueError('No saved observation image')
    root=Path(__file__).resolve().parents[2]
    output=Path(directory)/'observations'/uuid4().hex
    process=await asyncio.create_subprocess_exec(str(root/'shape-scanner/.venv/bin/python'),
        str(Path(__file__).with_name('gallery.py')),stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        stdout,_=await asyncio.wait_for(process.communicate(json.dumps(dict(scene=scene,
            detection_ids=[c['detection_id'] for c in ranked],output=str(output))).encode()),20)
    except BaseException:
        if process.returncode is None:process.kill()
        await process.wait();raise
    result=json.loads(stdout)
    if process.returncode or result.get('error'):raise ValueError(result.get('error','Observation images unavailable'))
    return result
