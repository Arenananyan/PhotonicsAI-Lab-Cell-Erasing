"""Demo questions remain read-only and never fall through to wiping."""
import tempfile
import unittest
from agents.llm import GroqAgents, TASK
from agents.workflow import Workflow
from jsonschema import validate
from test_status_speed import StatusPrinter


class DemoQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_lab_question_uses_facts_without_preparing_motion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools=StatusPrinter()
            flow=Workflow(tools,GroqAgents(demo=True),tmp,demo=True)
            rid=flow.new('Where is the print head?')
            await flow.prepare(rid)
            result=flow.get(rid)
            self.assertEqual(result['state'],'observed',result)
            self.assertIn('simulated',result['answer_message'])
            self.assertIn('20.0',result['answer_message'])
            self.assertIn('Blue cells: 2',result['answer_message'])
            self.assertFalse(tools.moves)
            self.assertFalse(any(name.startswith('preview') or name=='execute_sequence' for name,args in tools.calls))

    async def test_general_demo_question_is_explicitly_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools=StatusPrinter()
            flow=Workflow(tools,GroqAgents(demo=True),tmp,demo=True)
            rid=flow.new('What is the capital of France?')
            await flow.prepare(rid)
            self.assertEqual(flow.get(rid)['state'],'rejected')
            self.assertEqual(tools.calls,[])

    def test_unrecognized_demo_text_never_defaults_to_wiping(self):
        result=GroqAgents(demo=True)._demo('coordinator',{'user_request':'Hello, tell me a joke.'})
        self.assertEqual(result['action'],'reject')

    def test_question_mark_does_not_replace_explicit_cleaning_intent(self):
        result=GroqAgents(demo=True)._demo('coordinator',{'user_request':'Can you clean the largest blue cell?'})
        validate(result,TASK)
        self.assertEqual(result['action'],'wipe')

    def test_missing_observation_does_not_become_zero_cells(self):
        result=GroqAgents(demo=True)._demo('status_answer',{'user_request':'What is the printer status?', 'evidence':{'observation':{'available':False}}})
        self.assertIn('counts unavailable',result['message'])
        self.assertNotIn('cells: 0',result['message'])
