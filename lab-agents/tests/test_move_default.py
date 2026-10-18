import tempfile
import unittest
from agents.contracts import validate_task
from agents.workflow import Workflow
from test_autonomous import Printer,Scripted,task

class MoveDefault(unittest.IsolatedAsyncioTestCase):
    async def test_nullable_model_reply_gets_printer_default_and_requires_approval(self):
        for system in (None,'printer','paper'):
            with self.subTest(system=system),tempfile.TemporaryDirectory() as tmp:
                intent=dict(task('move',coordinates={'x':40,'y':60,'z':100}),coordinate_system=system)
                tools=Printer();flow=Workflow(tools,Scripted(intent),tmp,demo=True)
                rid=flow.new('Գնա x = 40, y = 60, z = 100:');await flow.prepare(rid)
                run=flow.get(rid)
                self.assertEqual(run['state'],'awaiting_confirmation',run.get('error'))
                self.assertEqual(run['task']['coordinate_system'],system or 'printer')
                self.assertEqual(run['plan']['destination'],[49,68,100] if system=='paper' else [40,60,100])
                self.assertFalse(tools.moves)
                flow.approve(rid,True,True);await flow.execute(rid)
                self.assertEqual(flow.get(rid)['state'],'completed')
                self.assertEqual(tools.position,run['plan']['destination'])

    def test_missing_default_does_not_accept_unknown_or_missing_xyz(self):
        intent=task('move',coordinates={'x':40,'y':60,'z':100});intent.pop('coordinate_system')
        self.assertEqual(validate_task(intent)['coordinate_system'],'printer')
        for system in ('camera','',False):
            with self.assertRaises(ValueError):validate_task(dict(intent,coordinate_system=system))
        with self.assertRaises(ValueError):validate_task(dict(intent,coordinates={'x':40,'y':60}))
