import tempfile
import unittest
from agents.llm import GroqAgents
from agents.workflow import Workflow
from agents.contracts import validate_task
from agents.planning import HOME
from test_autonomous import Printer

class HomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_without_camera_or_vision_and_single_approval(self):
        class NoVision(GroqAgents):
            async def check_vision(self):raise AssertionError('Home must not require vision')
        for prompt in ('Գնա տուն','Գնա «տուն»','վերադարձիր տուն','go home','return home'):
            with self.subTest(prompt=prompt),tempfile.TemporaryDirectory() as tmp:
                tools=Printer();flow=Workflow(tools,NoVision(demo=True),tmp,demo=True)
                rid=flow.new(prompt);await flow.prepare(rid)
                run=flow.get(rid)
                self.assertEqual(run['state'],'awaiting_confirmation',run)
                self.assertEqual(run['task']['action'],'home')
                self.assertEqual(run['plan']['destination'],HOME)
                self.assertEqual(run['plan']['steps'][0]['axis'],'z')
                self.assertFalse(tools.moves)
                flow.approve(rid,True,True);await flow.execute(rid)
                self.assertEqual(flow.get(rid)['state'],'completed')
                self.assertEqual(tools.position,HOME)
                self.assertEqual(len(tools.moves),1)
                self.assertEqual(flow.get(rid)['results'],[])
    async def test_home_cannot_inject_coordinates(self):
        with self.assertRaises(ValueError):
            validate_task(dict(action='home',coordinates=dict(x=1,y=2,z=3),message='Home'))
