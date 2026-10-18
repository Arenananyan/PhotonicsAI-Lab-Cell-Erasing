import json
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from agents.llm import GroqAgents,MESSAGE
from jsonschema import ValidationError

class StatusTransport(unittest.TestCase):
    def test_status_uses_json_not_forced_motion_tool(self):
        agent=GroqAgents();client=Mock()
        client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'message':'There are 3 cells.'})))])
        agent._client=lambda:client
        result=agent._request('status_answer',{'user_request':'How many cells?','evidence':{'observation':{'counts':{'blue':2,'green':1}}}},MESSAGE)
        self.assertEqual(result['message'],'There are 3 cells.')
        kwargs=client.chat.completions.create.call_args.kwargs
        self.assertNotIn('tools',kwargs);self.assertNotIn('tool_choice',kwargs)
        self.assertEqual(kwargs['response_format'],{'type':'json_object'})
        client.chat.completions.create.assert_called_once()

    def test_invalid_status_reply_is_not_accepted(self):
        agent=GroqAgents();client=Mock();agent._client=lambda:client
        for content in ('not json','{"message":""}','{"message":"ok","command":"move"}'):
            client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
            with self.assertRaises((ValueError,ValidationError)):agent._request('status_answer',{},MESSAGE)

    def test_vision_preflight_instruction_does_not_leak_into_assessment(self):
        agent=GroqAgents();client=Mock();agent._client=lambda:client
        client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"verdict":"uncertain","message":"test"}'))])
        agent._vision({'preflight':True},['data:image/png;base64,test'])
        preflight=client.chat.completions.create.call_args.kwargs['messages'][1]['content'][0]['text']
        self.assertIn('preflight only: return uncertain',preflight)
        agent._vision({'remaining_fraction':0},['before','after'])
        assessment=client.chat.completions.create.call_args.kwargs['messages'][1]['content'][0]['text']
        self.assertNotIn('Preflight',assessment)
        self.assertNotIn('preflight only',assessment)
        self.assertIn('Evaluate the actual remaining ink',assessment)
