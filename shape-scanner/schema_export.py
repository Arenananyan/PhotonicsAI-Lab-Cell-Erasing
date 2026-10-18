"""Export the same schemas enforced by the scanner/MCP result models."""
import json
from pathlib import Path
from camera_vision.models import FrameInfo, ScanResult, ErrorResponse

if __name__ == '__main__':
    directory = Path(__file__).parent/'schemas'
    directory.mkdir(exist_ok=True)
    for name, model in [('frame',FrameInfo),('scan-result',ScanResult),('error',ErrorResponse)]:
        (directory/(name+'.schema.json')).write_text(json.dumps(model.model_json_schema(), indent=2)+'\n')
