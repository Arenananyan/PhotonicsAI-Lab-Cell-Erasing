import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from printer_client import MockPrinter
from printer_commands import PrinterCommands


class SchemaTests(unittest.TestCase):
    def test_request_and_response_schema_examples(self):
        path = Path(__file__).resolve().parents[1] / 'docs' / 'printer-interface.schema.json'
        schema = json.loads(path.read_text())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        controller = PrinterCommands(MockPrinter())
        self.addCleanup(controller.close)
        move = {'command': 'move', 'target': {'x': 110, 'y': 120, 'z': 15}, 'speed_mm_s': 30}
        for request in (move, {'command': 'status'}, {'command': 'position'}, {'command': 'capabilities'},
                        {'command': 'home'}, {'command': 'job', 'job_id': 'unknown'}, {'command': 'stop'}):
            with self.subTest(request=request):
                validator.validate(request)
                validator.validate(controller.execute(request))
        self.assertFalse(validator.is_valid(dict(move, e=1)))
        self.assertFalse(validator.is_valid(dict(move, speed_mm_s=31)))
        self.assertFalse(validator.is_valid(dict(move, preview=False)))
