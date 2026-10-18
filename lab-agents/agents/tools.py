"""Two independent stdio MCP clients. Hardware motion stays disabled by default."""
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import sys
from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

ROOT=Path(__file__).resolve().parents[2]


class Tools:
    def __init__(self, mode='mock'):
        if mode not in ('mock','real'): raise ValueError('Invalid printer mode')
        self.mode=mode
        self.stack=AsyncExitStack()

    async def open(self):
        try:
            env=dict(PRINTER_MODE=self.mode,PRINTER_ALLOW_MOTION=os.getenv('PRINTER_ALLOW_MOTION','0'))
            # Auth remains exclusively in the operator's shared SSH session.
            for name in ('SSH_HOST','SSH_CONTROL_PATH'):
                if name in os.environ: env[name]=os.environ[name]
            self.printer=await self.stack.enter_async_context(Client(PythonStdioTransport(
                ROOT/'photonics-printer-mcp-main/fastmcp_server.py', python_cmd=sys.executable,
                cwd=str(ROOT/'photonics-printer-mcp-main'),env=env),timeout=120))
            self.scanner=await self.stack.enter_async_context(Client(PythonStdioTransport(
                ROOT/'shape-scanner/cells_mcp_server.py',
                python_cmd=str(ROOT/'shape-scanner/.venv/bin/python'),
                cwd=str(ROOT/'shape-scanner'),env={'CAMERA_VISION_URL':os.getenv('CAMERA_VISION_URL','http://127.0.0.1:8767')}),timeout=25))
            return self
        except BaseException:
            await self.stack.aclose()
            raise

    async def close(self): await self.stack.aclose()

    async def call(self,server,name,arguments=None):
        client=self.printer if server=='printer' else self.scanner
        reply=await client.call_tool(name,arguments or {})
        data=reply.data
        if hasattr(data,"model_dump"):
            data=data.model_dump()
        if not isinstance(data,dict) and isinstance(reply.structured_content,dict):
            data=reply.structured_content
        if data is None:
            texts=[block.text for block in reply.content if getattr(block,'type',None)=='text']
            if texts: data=json.loads(texts[0])
        if not isinstance(data,dict): raise RuntimeError('MCP tool did not return an object: '+name)
        if data.get('ok') is False: raise RuntimeError(str(data.get('error',data)))
        return data
