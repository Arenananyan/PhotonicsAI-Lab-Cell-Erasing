import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import httpx
from groq import BadRequestError
from agents.workflow import Workflow
from agents.llm import GroqAgents,TASK
from test_autonomous import Scripted,task
from test_status_speed import StatusPrinter


def find_green():return dict(task('inspect',color='green',selection='largest'))


class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_composed_find_is_readonly_and_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec=dict(task('inspect',color='blue',selection='nearest'),reference=dict(color='green',selection='largest'))
            tools=StatusPrinter();flow=Workflow(tools,Scripted(spec),tmp,demo=True)
            rid=flow.new('find the biggest green cell and from that point find the nearest blue cell',chat_id='chat-a')
            await flow.prepare(rid);r=flow.get(rid)
            self.assertEqual(r['state'],'observed',r.get('error'))
            self.assertEqual(r['selected_targets'][0]['color'],'blue')
            self.assertEqual(r['selected_targets'][0]['printer_coordinates_mm'],dict(x=160.,y=130.))
            self.assertEqual(len(r['distances']),1)
            self.assertAlmostEqual(r['distances'][0]['distance_mm'],67.0820393)
            self.assertFalse(tools.moves);self.assertNotIn('plan',r)

    async def test_followup_reobserves_and_previews_only_same_chat_with_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools=StatusPrinter();agent=Scripted(find_green());flow=Workflow(tools,agent,tmp,demo=True)
            first=flow.new('find biggest green',chat_id='one');await flow.prepare(first)
            selected=flow.get(first)['selected_targets'][0]
            self.assertEqual(selected['color'],'green')
            # A restarted process can read saved facts, but cannot resume an old path.
            agent.task=dict(task('move',None,None),use_previous_target=True,coordinate_system=None)
            flow=Workflow(tools,agent,tmp,demo=True)
            rid=flow.new('go to that point',chat_id='one',previous_run_ids=[first]);await flow.prepare(rid)
            r=flow.get(rid)
            self.assertEqual(r['state'],'awaiting_confirmation',r.get('error'))
            self.assertEqual(r['plan']['waypoints'][-1],[100.,100.,100])
            self.assertFalse(tools.moves)
            flow.approve(rid,True,True);await flow.execute(rid)
            self.assertEqual(tools.moves,[[100.,100.,100.]])
            other=flow.new('go to that point',chat_id='two',previous_run_ids=[first]);await flow.prepare(other)
            self.assertEqual(flow.get(other)['state'],'awaiting_answer')
            self.assertEqual(flow.conversation(other),[])
            self.assertEqual(len(tools.moves),1)

    async def test_missing_changed_target_never_moves(self):
        from unittest.mock import patch,AsyncMock
        from agents.observation import synthetic_scene
        with tempfile.TemporaryDirectory() as tmp:
            tools=StatusPrinter();agent=Scripted(find_green());flow=Workflow(tools,agent,tmp,demo=True)
            first=flow.new('find',chat_id='one');await flow.prepare(first)
            agent.task=dict(task('move',None,None),use_previous_target=True,coordinate_system=None)
            missing=synthetic_scene(1);missing['detections']=missing['detections'][:2]
            with patch.object(flow,'cell_scene',new=AsyncMock(return_value=dict(cells=missing['detections'],frame_id='f',calibration_id='synthetic'))):
                rid=flow.new('go there',chat_id='one');await flow.prepare(rid)
            self.assertEqual(flow.get(rid)['state'],'awaiting_answer');self.assertFalse(tools.moves)


class ProposalRecovery(unittest.TestCase):
    def test_tool_generation_400_uses_one_validated_json_proposal(self):
        client=Mock();agent=GroqAgents();agent._client=lambda:client
        error=BadRequestError('failed',response=httpx.Response(400,request=httpx.Request('POST','https://api.groq.com/test')),
                              body={'error':{'code':'tool_use_failed'}})
        spec=find_green()
        reply=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(spec)))])
        client.chat.completions.create.side_effect=[error,reply]
        self.assertEqual(agent._request('coordinator',{'user_request':'find biggest green'},TASK),spec)
        self.assertEqual(client.chat.completions.create.call_count,2)
        self.assertNotIn('tools',client.chat.completions.create.call_args.kwargs)
        # Invalid provider proposals still cannot get through validation.
        reply.choices[0].message.content='{"action":"send_gcode","message":"bad"}'
        client.chat.completions.create.side_effect=[error,reply]
        with self.assertRaises(Exception):agent._request('coordinator',{},TASK)

    def test_other_400_errors_do_not_loop(self):
        client=Mock();agent=GroqAgents();agent._client=lambda:client
        client.chat.completions.create.side_effect=BadRequestError('failed',response=httpx.Response(400,request=httpx.Request('POST','https://api.groq.com/test')),
                                                                  body={'code':'invalid_request_error'})
        with self.assertRaisesRegex(RuntimeError,'invalid_request_error'):agent._request('coordinator',{},TASK)
        client.chat.completions.create.assert_called_once()
