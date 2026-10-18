"""Coupled XY segments retain all bounds and preflight checks."""
import unittest
from printer_client import MockPrinter, mock_state
from printer_policy import plan, SafetyError

class XYSegments(unittest.TestCase):
    def test_coupled_leg_is_one_line(self):
        p=plan(mock_state(),[{'axis':'xy','distance_mm':[3,4]}],20)
        self.assertEqual(p['targets'],[[103,104,5]])
        self.assertAlmostEqual(p['nominal_seconds'],.25)
        self.assertEqual(p['script'],'G90\nG1 X103.000 Y104.000 F1200.000000\nM400')

    def test_invalid_vectors_rejected(self):
        for delta in (3,[1],[1,2,3],[True,1],[float('nan'),0],
                      [0,float('inf')],[0,0],[.0001,.0001]):
            with self.subTest(delta=delta), self.assertRaises(SafetyError):
                plan(mock_state(),[{'axis':'xy','distance_mm':delta}],20)

    def test_full_circle_bounds_checked(self):
        # Center is reachable; one side of the circle exceeds X firmware max.
        steps=[{'axis':'xy','distance_mm':[115,0]},
               {'axis':'xy','distance_mm':[10,10]},
               {'axis':'xy','distance_mm':[-10,-10]}]
        with self.assertRaises(SafetyError): plan(mock_state(),steps,20)

    def test_mock_sequence_and_offset_guard(self):
        p=MockPrinter()
        req={'action':'preview','steps':[{'axis':'xy','distance_mm':[3,4]}],'speed_mm_s':20}
        result=p.request(req)
        self.assertEqual(result['plan']['end'],[103,104,5])
        p.state['gcode_move']['homing_origin'][2]=.01
        with self.assertRaises(SafetyError): p.request(req)
