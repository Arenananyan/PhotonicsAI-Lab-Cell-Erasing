"""MCP bridge for the running shape scanner. Transport: stdio."""
import json
import os
import urllib.error
import urllib.request
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver import Image
from pydantic import BaseModel

mcp = MCPServer('Lab Shape Scanner')
BASE_URL = os.environ.get('SHAPE_SCANNER_URL', 'http://127.0.0.1:8766').rstrip('/')


class Detection(BaseModel):
    number: int
    shape: Literal['triangle', 'quadrilateral']


class Counts(BaseModel):
    triangle: int
    quadrilateral: int


class Observation(BaseModel):
    ok: bool
    observed_at: str
    frame: int
    age_seconds: float
    counts: Counts
    detections: list[Detection]
    method: str


def fetch(path):
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=5) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode(errors='replace')) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError('Start the shape scanner and camera preview first: ' + str(exc)) from exc


@mcp.tool()
def detect_shapes() -> Observation:
    """Read current black-outline triangle/quadrilateral detections and counts.

    Requires camera-control preview and the separate shape scanner running.
    Returns a recent observation; no printer coordinates or tracking IDs.
    Cannot see arbitrary objects. An unavailable camera raises an error.
    """
    return Observation.model_validate_json(fetch('/api/detections'))


@mcp.tool()
def get_annotated_image() -> Image:
    """View the latest camera frame with triangle/quadrilateral outlines and labels."""
    return Image(data=fetch('/snapshot.jpg'), format='jpeg')


if __name__ == '__main__':
    mcp.run()
