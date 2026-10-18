"""LLM/JSON interface tests without physical printer I/O."""
import copy
import json
from pathlib import Path
import subprocess
import threading
import time
import unittest
from unittest.mock import Mock, patch

from printer_client import MockPrinter, PrinterError, mock_state
from printer_commands import PrinterCommands, error_info, parse_command
from printer_policy import SafetyError, check_execution_state, plan, plan_absolute
from printer_watchdog import AUDITED_HOMING_SIGNATURE, execute_home, polling_objects, prepare_home, snapshot
from test_simple import FakeAPI


MOVE = {'command': 'move', 'target': {'x': 110, 'y': 120, 'z': 15}, 'speed_mm_s': 30}


class CommandsTests(unittest.TestCase):
    def setUp(self):
        self.printer = MockPrinter()
        self.controller = PrinterCommands(self.printer)
        self.addCleanup(self.controller.close)

    def preview(self, command=None):
        response = self.controller.execute(command or MOVE)
        self.assertTrue(response['ok'], response)
        self.assertEqual(response['status'], 'previewed')
        return response['data']['token']

    def execute_move(self, token, command=None):
        return self.controller.execute(dict(command or MOVE, token=token, preview=False, operator_confirmed=True))

    def poll(self, response):
        self.assertTrue(response['ok'], response)
        self.assertEqual(response['status'], 'accepted')
        self.controller.close()
        return self.controller.execute({'command': 'job', 'job_id': response['data']['job_id']})

    def test_move_preview_execution_job_and_single_use(self):
        token = self.preview()
        self.assertEqual(self.printer.submitted_scripts, [])
        result = self.poll(self.execute_move(token))
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(result['data']['result']['position_mm'], {'x': 110, 'y': 120, 'z': 15})
        self.assertEqual(self.printer.submitted_scripts, ['G90\nG1 X110.000 Y120.000 Z15.000 F1800.000000\nM400'])
        again = self.execute_move(token)
        self.assertEqual(again['error']['code'], 'TOKEN_INVALID')

    def test_omitted_speed_defaults_to_20_and_execution_inherits_preview(self):
        command = {'command': 'move', 'target': MOVE['target']}
        token = self.preview(command)
        self.assertEqual(self.controller.tokens[token]['plan']['speed_mm_s'], 20)
        result = self.poll(self.execute_move(token, command))
        self.assertTrue(result['ok'], result)
        command = dict(MOVE, speed_mm_s=3.333333333)
        token = self.preview(command)
        result = self.poll(self.execute_move(token, {'command': 'move', 'target': MOVE['target']}))
        self.assertTrue(result['ok'], result)

    def test_expiry_confirmation_and_changed_plan(self):
        token = self.preview()
        request = dict(MOVE, preview=False, token=token)
        self.assertEqual(self.controller.execute(request)['error']['code'], 'CONFIRMATION_REQUIRED')
        changed = dict(request, operator_confirmed=True, speed_mm_s=25)
        self.assertEqual(self.controller.execute(changed)['error']['code'], 'PREVIEW_CHANGED')
        self.controller.tokens[token]['expires'] = 0
        self.assertEqual(self.execute_move(token)['error']['code'], 'TOKEN_INVALID')
        self.assertEqual(self.printer.submitted_scripts, [])

    def test_invalid_commands_never_contact_printer(self):
        invalid = [None, [], {'command': 'heat'}, dict(MOVE, e=1), dict(MOVE, acceleration=99999),
                   dict(MOVE, target={'x': True, 'y': 120, 'z': 15}),
                   dict(MOVE, speed_mm_s=31), dict(MOVE, speed_mm_s=True),
                   dict(MOVE, speed_mm_s=float('nan')), dict(MOVE, preview='false'),
                   dict(MOVE, id={}), {'command': 'home', 'axes': ['x', 'x']},
                   {'command': 'home', 'axes': [{}]}, {'command': 'job'},
                   {'command': 'stop', 'script': 'G28'}, dict(MOVE, token='abc')]
        with patch.object(self.printer, 'request', side_effect=AssertionError('Printer accessed')):
            for request in invalid:
                with self.subTest(request=request):
                    response = self.controller.execute(request)
                    self.assertFalse(response['ok'], response)
                    self.assertEqual(response['status'], 'error')
                    self.assertFalse(response['error']['retryable'])

    def test_stale_start_fails_job_without_movement_or_stop(self):
        token = self.preview()
        for obj, field in (('toolhead', 'position'), ('motion_report', 'live_position'),
                           ('gcode_move', 'position'), ('gcode_move', 'gcode_position')):
            self.printer.state[obj][field][0] += 1
        result = self.poll(self.execute_move(token))
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'PREVIEW_CHANGED')
        self.assertEqual(self.printer.submitted_scripts, [])
        self.assertEqual(self.printer.state['webhooks']['state'], 'ready')

    def test_busy_rejection_reads_and_stop_remain_responsive(self):
        token = self.preview()
        entered, release = threading.Event(), threading.Event()
        original = self.printer.request
        def request(message):
            if message['action'] == 'absolute-move':
                entered.set()
                release.wait(3)
            return original(message)
        with patch.object(self.printer, 'request', side_effect=request):
            accepted = self.execute_move(token)
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.controller.execute(MOVE)['error']['code'], 'BUSY')
                self.assertEqual(self.controller.execute({'command': 'home'})['error']['code'], 'BUSY')
                position = self.controller.execute({'command': 'position'})
                self.assertTrue(position['ok'])
                self.assertTrue(position['data']['busy'])
                stopped = self.controller.execute({'command': 'stop'})
                self.assertEqual(stopped['status'], 'stopped')
            finally:
                release.set()
                self.controller.close()
            result = self.controller.execute({'command': 'job', 'job_id': accepted['data']['job_id']})
            self.assertEqual(result['status'], 'stopped')
            self.assertEqual(self.printer.submitted_scripts, [])

    def test_shared_motion_lock_blocks_new_commands(self):
        with self.controller.motion_lock:
            self.assertEqual(self.controller.execute(MOVE)['error']['code'], 'BUSY')
            self.assertTrue(self.controller.execute({'command': 'status'})['ok'])

    def test_real_motion_and_home_mode_gates(self):
        token = self.preview()
        self.printer.simulated = False
        with patch.dict('os.environ', {'PRINTER_ALLOW_MOTION': '0'}):
            self.assertEqual(self.execute_move(token)['error']['code'], 'MOTION_DISABLED')
        self.assertEqual(self.controller.execute({'command': 'home'})['error']['code'], 'HOME_CONFIGURATION_REQUIRED')
        self.assertEqual(self.printer.submitted_scripts, [])

    def test_homing_preview_confirmation_and_result(self):
        self.printer.state['toolhead']['homed_axes'] = ''
        self.assertEqual(self.controller.execute(MOVE)['error']['code'], 'NOT_HOMED')
        request = {'command': 'home', 'axes': ['x', 'y', 'z']}
        token = self.preview(request)
        result = self.poll(self.controller.execute(dict(request, preview=False, token=token, operator_confirmed=True)))
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['data']['result']['homed_axes'], 'xyz')
        self.assertEqual(self.printer.submitted_scripts, ['G28 X Y Z\nM400'])

    def test_stop_invalidates_previews_and_legacy_callback(self):
        token = self.preview()
        callback = Mock()
        self.controller.on_invalidate = callback
        result = self.controller.execute({'command': 'stop'})
        self.assertTrue(result['ok'])
        self.assertNotIn(token, self.controller.tokens)
        callback.assert_called_once()

    def test_stop_during_preview_invalidates_new_token(self):
        entered, release = threading.Event(), threading.Event()
        original = self.printer.request
        def request(message):
            reply = original(message)
            if message['action'] == 'absolute-preview':
                entered.set()
                release.wait(3)
            return reply
        replies = []
        with patch.object(self.printer, 'request', side_effect=request):
            worker = threading.Thread(target=lambda: replies.append(self.controller.execute(MOVE)))
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.controller.execute({'command': 'stop'})['ok'])
            finally:
                release.set()
                worker.join(3)
        self.assertEqual(replies[0]['error']['code'], 'TOKEN_INVALID')
        self.assertEqual(self.controller.tokens, {})

    def test_stop_unconfirmed_and_unknown_job(self):
        with patch.object(self.printer, 'request', return_value={'ok': False, 'stop_confirmed': False}):
            result = self.controller.execute({'command': 'stop'})
        self.assertEqual(result['error']['code'], 'STOP_UNCONFIRMED')
        self.assertEqual(self.controller.execute({'command': 'job', 'job_id': 'unknown'})['error']['code'], 'JOB_NOT_FOUND')

    def test_capabilities_and_public_plan_do_not_expose_gcode(self):
        caps = self.controller.execute({'command': 'capabilities'})['data']
        self.assertEqual(caps['coordinate_units'], 'mm')
        self.assertEqual(caps['speed_units'], 'mm/s')
        self.assertEqual(caps['acceleration_control'], 'firmware')
        response = self.controller.execute(MOVE)
        self.assertNotIn('script', response['data']['plan'])
        self.assertEqual(response['data']['plan']['speed_mm_s'], 30)

    def test_uncertain_motion_has_stop_confirmation_details(self):
        token = self.preview()
        original = self.printer.request
        def request(message):
            if message['action'] == 'absolute-move':
                raise PrinterError('Connection lost')
            return original(message)
        with patch.object(self.printer, 'request', side_effect=request):
            result = self.poll(self.execute_move(token))
        self.assertEqual(result['error']['code'], 'OUTCOME_UNCERTAIN')
        self.assertTrue(result['error']['details']['command_may_have_executed'])
        self.assertTrue(result['error']['details']['stop_requested'])
        self.assertTrue(result['error']['details']['stop_confirmed'])

    def test_backend_diagnostics_are_preserved_in_json_errors(self):
        diagnostics = {'startup_window_seconds': 0.5, 'recent_telemetry': [{'live_position': [0, 0, 0]}]}
        error = PrinterError(json.dumps({'ok': False, 'error': 'No confirmed live position',
                                        'command_may_have_executed': True, 'stop_confirmed': True,
                                        'diagnostics': diagnostics}))
        info = error_info(error)
        self.assertEqual(info['code'], 'OUTCOME_UNCERTAIN')
        self.assertEqual(info['details']['diagnostics'], diagnostics)

    def test_ndjson_cli_handles_malformed_input_and_continues(self):
        root = Path(__file__).resolve().parents[1]
        lines = ['{bad json', '{"command":"position","command":"stop"}',
                 '{"command":"move","target":{"x":NaN,"y":100,"z":5}}',
                 json.dumps({'command': 'position', 'id': 'position-read'})]
        result = subprocess.run([str(root / 'printerctl'), 'json', '--mock'],
                                input='\n'.join(lines) + '\n', capture_output=True, text=True, cwd='/tmp')
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses), 4)
        self.assertTrue(all(item['error']['code'] == 'INVALID_JSON' for item in responses[:3]))
        self.assertEqual(responses[-1]['id'], 'position-read')
        self.assertTrue(responses[-1]['ok'])

    def test_ndjson_cli_move_roundtrip(self):
        root = Path(__file__).resolve().parents[1]
        process = subprocess.Popen([str(root / 'printerctl'), 'json', '--mock'], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd='/tmp')
        def call(request):
            process.stdin.write(json.dumps(request) + '\n')
            process.stdin.flush()
            return json.loads(process.stdout.readline())
        try:
            preview = call(MOVE)
            accepted = call(dict(MOVE, preview=False, token=preview['data']['token'], operator_confirmed=True))
            deadline = time.monotonic() + 3
            while True:
                result = call({'command': 'job', 'job_id': accepted['data']['job_id']})
                if result['status'] != 'running':
                    break
                self.assertLess(time.monotonic(), deadline)
            self.assertEqual(result['status'], 'completed', result)
        finally:
            process.stdin.close()
            process.stdin = None
            output, error = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, error)
        self.assertEqual(output, '')


class FirmwareLimitsTests(unittest.TestCase):
    def test_faster_move_requires_verified_limits(self):
        state = mock_state()
        self.assertEqual(plan_absolute(state, MOVE['target'], 30)['speed_mm_s'], 30)
        state.pop('motion_limits')
        with self.assertRaisesRegex(SafetyError, 'verified firmware'):
            plan_absolute(state, MOVE['target'], 30)
        self.assertEqual(plan_absolute(state, MOVE['target'], 20)['speed_mm_s'], 20)

    def test_lower_z_firmware_limit_and_invalid_acceleration(self):
        state = mock_state()
        state['motion_limits']['max_z_velocity'] = 10
        with self.assertRaisesRegex(SafetyError, 'firmware'):
            plan_absolute(state, MOVE['target'], 20)
        self.assertEqual(plan_absolute(state, {'x': 110, 'y': 120, 'z': 5}, 30)['speed_mm_s'], 30)
        with self.assertRaises(SafetyError):
            plan(state, [{'axis': 'z', 'distance_mm': 5}], 20, 20)
        state['motion_limits']['max_accel'] = float('nan')
        with self.assertRaises(SafetyError):
            plan_absolute(state, MOVE['target'], 5)

    def test_dynamic_acceleration_cannot_exceed_configured_cap(self):
        state = mock_state()
        prepared = plan_absolute(state, MOVE['target'], 30)
        state['toolhead']['max_accel'] = 8001
        with self.assertRaisesRegex(SafetyError, 'acceleration'):
            plan_absolute(state, MOVE['target'], 30)
        with self.assertRaisesRegex(SafetyError, 'acceleration'):
            check_execution_state(state, prepared)

    def test_snapshot_filters_full_configuration(self):
        api = Mock()
        state = mock_state()
        state['configfile'] = {'settings': {'printer': state['motion_limits'], 'private_section': {'value': 'private'}}}
        api.call.return_value = {'status': state, 'eventtime': 1}
        result, stamp = snapshot(api, {})
        self.assertEqual(stamp, 1)
        self.assertNotIn('configfile', result)
        self.assertNotIn('private_section', result)
        self.assertEqual(result['motion_limits']['max_z_velocity'], 30)


class HomingBackendTests(unittest.TestCase):
    def report(self):
        return {'homing_signature': AUDITED_HOMING_SIGNATURE}

    def test_homing_polls_keep_live_lift_variable_without_full_configuration(self):
        objects = {'configfile': ['settings'], 'gcode_macro XYZ_READY': ['safe_z'],
                   'toolhead': None, 'motion_report': None}
        result = polling_objects(objects, homing=True)
        self.assertNotIn('configfile', result)
        self.assertIn('gcode_macro XYZ_READY', result)

    def test_changed_homing_profile_rejected_before_dispatch(self):
        api = FakeAPI()
        with patch('printer_watchdog.capabilities', return_value={'homing_signature': 'changed'}):
            with self.assertRaisesRegex(SafetyError, 'operator review'):
                prepare_home(api, api.state, ['x', 'y', 'z'])
        self.assertEqual(api.calls, [])

    def test_changed_runtime_homing_lift_rejected(self):
        api = FakeAPI()
        api.state['homing_lift_mm'] = 20
        with patch('printer_watchdog.capabilities', return_value=self.report()):
            with self.assertRaisesRegex(SafetyError, 'Z-lift variable'):
                prepare_home(api, api.state, ['x', 'y', 'z'])
        self.assertEqual(api.calls, [])


    def test_homing_completion_and_no_heating_or_extrusion(self):
        api, stop = FakeAPI(), Mock(return_value=True)
        api.state['toolhead']['homed_axes'] = ''
        def mutate(state):
            state['toolhead']['homed_axes'] = 'xyz'
        api.mutation = mutate
        request = {'action': 'home', 'axes': ['x', 'y', 'z'], 'expected_start': [100, 100, 5],
                   'expected_homed_axes': '', 'homing_signature': AUDITED_HOMING_SIGNATURE}
        with patch('printer_watchdog.capabilities', return_value=self.report()):
            result = execute_home(api, {}, request, stop, 0)
        self.assertTrue(result['ok'], result)
        self.assertEqual(api.calls, [('gcode/script', {'script': 'G28 X Y Z\nM400'})])
        stop.assert_not_called()

    def test_homing_heat_or_extrusion_fault_requests_stop(self):
        for field in ('heater', 'extrusion'):
            def mutate(state):
                if field == 'heater':
                    state['extruder']['target'] = 200
                else:
                    state['gcode_move']['position'][3] = 1
            api, stop = FakeAPI(mutate), Mock(return_value=True)
            request = {'action': 'home', 'axes': ['x'], 'expected_start': [100, 100, 5],
                       'expected_homed_axes': 'xyz', 'homing_signature': AUDITED_HOMING_SIGNATURE}
            with self.subTest(field=field), patch('printer_watchdog.capabilities', return_value=self.report()):
                result = execute_home(api, {}, request, stop, 0)
            self.assertFalse(result['ok'])
            self.assertTrue(result['stop_confirmed'])
            stop.assert_called_once()

    def test_homing_start_change_and_active_heater_prevent_dispatch(self):
        for mutation in ('start', 'heater'):
            api, stop = FakeAPI(), Mock()
            request = {'action': 'home', 'axes': ['x'], 'expected_start': [100, 100, 5],
                       'expected_homed_axes': 'xyz', 'homing_signature': AUDITED_HOMING_SIGNATURE}
            if mutation == 'start':
                request['expected_start'][0] = 99
            else:
                api.state['heater_bed']['target'] = 60
            with self.subTest(mutation=mutation), patch('printer_watchdog.capabilities', return_value=self.report()):
                with self.assertRaises(SafetyError):
                    execute_home(api, {}, request, stop, 0)
            self.assertEqual(api.calls, [])
            stop.assert_not_called()
