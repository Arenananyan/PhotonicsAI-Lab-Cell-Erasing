"""Real stdio MCP integration against a local hardware-free HTTP scanner."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from mcp import Client, StdioServerParameters
from werkzeug.serving import make_server
from camera_vision.live import LiveScanner
from camera_vision.service import ScanService
from camera_vision.web import create_app


class MCPIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_scan_image_and_errors_over_stdio(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ScanService(Path(directory))
            app = create_app(service, LiveScanner(service, demo=True))
            server = make_server('127.0.0.1', 0, app, threaded=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            params = StdioServerParameters(command=sys.executable,
                args=[str(Path(__file__).resolve().parents[1]/'cells_mcp_server.py')],
                env={'CAMERA_VISION_URL': f'http://127.0.0.1:{server.server_port}'})
            try:
                async with Client(params) as client:
                    tools = await client.list_tools()
                    names = {tool.name for tool in tools.tools}
                    self.assertEqual(len(names), 24)
                    self.assertIn('scanner_detect_board_border',names)
                    self.assertIn('camera_capture_frame', names)
                    self.assertIn('scanner_scan_saved_frame', names)
                    captured = await client.call_tool('camera_capture_frame')
                    self.assertFalse(captured.is_error)
                    frame_id = captured.structured_content['frame_id']
                    result = await client.call_tool('scanner_scan_saved_frame', {'frame_id': frame_id})
                    self.assertFalse(result.is_error)
                    data = result.structured_content
                    self.assertEqual(data['frame_id'], frame_id)
                    self.assertEqual(data['coordinate_space'], 'image_pixels')
                    self.assertEqual(data['counts'], {'defective': 2, 'healthy': 2})
                    self.assertTrue(all(cell['frame_id']==frame_id for cell in data['detections']))
                    raw = await client.call_tool('camera_get_frame_image', {'frame_id': frame_id})
                    self.assertFalse(raw.is_error)
                    self.assertEqual(raw.content[0].mime_type, 'image/png')
                    image = await client.call_tool('scanner_get_annotated_image',
                        {'frame_id': frame_id, 'analysis_id': data['analysis_id']})
                    self.assertFalse(image.is_error)
                    self.assertEqual(image.content[0].type, 'image')
                    scan_file = await client.call_tool('scanner_analyze_image',
                        {'image_path': data['frame']['raw_image']})
                    self.assertFalse(scan_file.is_error)
                    self.assertEqual(scan_file.structured_content['counts'], data['counts'])
                    unavailable = await client.call_tool('camera_get_status')
                    self.assertTrue(unavailable.is_error)
                    self.assertIn('CAMERA_DISABLED', unavailable.content[0].text)
                    invalid = await client.call_tool('scanner_scan_saved_frame', {'frame_id': 'bad'})
                    self.assertTrue(invalid.is_error)
                    self.assertIn('INVALID_FRAME_ID', invalid.content[0].text)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
