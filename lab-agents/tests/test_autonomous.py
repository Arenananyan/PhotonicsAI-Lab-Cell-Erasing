import copy
from datetime import datetime,timezone,timedelta
import tempfile
import time
import unittest
from pathlib import Path
from agents.workflow import Workflow
from agents.llm import GroqAgents,TASK
from agents.contracts import validate_task,validate_selection,selected_cells,associate
from agents.planning import make_move_plan,HOME
from agents.observation import synthetic_scene,stable_scope


class Printer:
    mode='mock'
    def __init__(self): self.position=[20.,30.,40.];self.moves=[];self.tokens={}
    async def call(self,server,name,args=None):
        args=args or {}
        if name=='printer_status': return dict(state={'webhooks':{'state':'ready'}})
        if name=='printer_command': return dict(simulated=True,data={'position_mm':dict(zip('xyz',self.position))})
        if name in ('preview_sequence','preview_position'):
            end=self.position[:]
            for step in args.get('steps',[]):
                if step['axis']=='xy': end[0]+=step['distance_mm'][0];end[1]+=step['distance_mm'][1]
                else: end['xyz'.index(step['axis'])]+=step['distance_mm']
            if name=='preview_position':end=[args[a] for a in 'xyz']
            for value,lo,hi in zip(end,[-12,-20,-5],[221,223,246]):
                if not lo<=value<=hi: raise ValueError('Outside firmware bounds')
            token=str(len(self.tokens));self.tokens[token]=end
            return dict(start=self.position[:],token=token,simulated=True)
        if name=='execute_sequence':
            self.position=[round(v,3) for v in self.tokens.pop(args['token'])]
            self.moves.append(self.position[:]);return dict(ok=True,reported_position=self.position,simulated=True)
        raise ValueError('Unexpected tool '+name)


class Scripted(GroqAgents):
    def __init__(self,task=None,verdict='clean'):
        super().__init__(demo=True);self.task=task;self.verdict=verdict
    async def decide(self,role,evidence,contract):
        if role=='coordinator' and self.task:return copy.deepcopy(self.task)
        return await super().decide(role,evidence,contract)
    async def assess(self,evidence,images):return dict(verdict=self.verdict,message='Test result')


def task(action='wipe',color='blue',selection='all',coordinates=None):
    if action=='inspect' and color=='blue' and selection=='all':color=selection=None
    return dict(action=action,color=color,selection=selection,coordinates=coordinates,coordinate_system='printer',message='Test intent')


class Scopes(unittest.TestCase):
    def test_invalid_or_missing_coordinates(self):
        for coords in ({'x':1,'y':2},{'x':True,'y':2,'z':3},{'x':float('nan'),'y':2,'z':3}):
            with self.assertRaises(ValueError):validate_task(task('move',coordinates=coords))
    def test_move_clearance_and_paper_mapping(self):
        p=make_move_plan([1,2,150],dict(x=10,y=20,z=14.5),'paper')
        self.assertEqual(p['waypoints'],[[19,2,150],[19,28,150],[19,28,14.5]])
        self.assertEqual(make_move_plan([1,2,10],dict(x=20,y=30,z=140))['waypoints'][0],[1,2,140])
    def test_llm_must_select_actual_scope_without_duplicates(self):
        cells=synthetic_scene(1)['detections']
        for i,c in enumerate(cells):c['target_id']=str(i)
        for ids in (['fiction'],['0','0'],['2'],['0']):
            with self.assertRaises(ValueError):validate_selection(dict(target_ids=ids),cells,task())
        self.assertEqual(len(validate_selection(dict(target_ids=['1','0']),cells,task())),2)
        with self.assertRaises(ValueError):validate_selection(dict(target_ids=['1']),cells,task(selection='largest'))
    def test_missing_split_near_tie_and_stability(self):
        cells=synthetic_scene(1)['detections']
        with self.assertRaises(ValueError):associate(cells[0],[])
        with self.assertRaises(ValueError):associate(cells[0],[cells[0],copy.deepcopy(cells[0])])
        cells[1]['area_mm2']=149
        with self.assertRaises(ValueError):selected_cells(cells,task(selection='largest'))
        scenes=[synthetic_scene(i) for i in range(4)]
        scenes[1]['detections']=scenes[1]['detections'][:2]  # green flicker irrelevant to blue
        self.assertEqual(len(stable_scope(scenes,1,lambda c:selected_cells(c,task()))),3)
        scenes[2]['detections'][0]['printer_coordinates_mm']['x']+=5
        with self.assertRaises(ValueError):stable_scope(scenes,1,lambda c:selected_cells(c,task()))


class Autonomous(unittest.IsolatedAsyncioTestCase):
    async def run_flow(self,prompt,agents=None):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        tools=Printer();flow=Workflow(tools,agents or Scripted(),self.tmp.name,demo=True)
        rid=flow.new(prompt);await flow.prepare(rid)
        return flow,rid,tools
    async def test_all_blue_batch_and_single_target_approval(self):
        for prompt,count in [('Մաքրիր բոլոր կապույտները',2),('Clean all green',1),('Clean smallest blue',1),('Մաքրիր ամենափոքր կանաչը',1)]:
            flow,rid,tools=await self.run_flow(prompt)
            for _ in range(2):
                self.assertEqual(flow.get(rid)['state'],'awaiting_confirmation')
                flow.approve(rid,True,True);await flow.execute(rid)
            r=flow.get(rid)
            self.assertEqual(r['state'],'completed',r)
            self.assertEqual(len(r['results']),count)
            self.assertEqual(len(set(r['attempted'])),count)
            self.assertEqual(len(tools.moves),1+count)
            self.assertEqual(tools.position,HOME)
            with self.assertRaises(ValueError):flow.approve(rid,True,True)
    async def test_all_residue_finishes_queue_without_questions_or_repeats(self):
        flow,rid,tools=await self.run_flow('all blue',Scripted(verdict='residue'))
        flow.approve(rid,True,True);await flow.execute(rid)
        ready=flow.get(rid)
        self.assertEqual(ready['plan']['kind'],'batch_wipe')
        self.assertEqual(ready['plan']['target_count'],2)
        self.assertEqual(len(ready['batch_paths']),2)
        flow.approve(rid,True,True);await flow.execute(rid)
        r=flow.get(rid)
        self.assertEqual(r['state'],'completed')
        self.assertEqual([v['verdict'] for v in r['results']],['residue','residue'])
        self.assertEqual(len(tools.moves),3)
        self.assertEqual(len(set(r['attempted'])),2)
        self.assertIn('2/2',r['summary'])
        self.assertIn('մնացորդով՝ 2',r['summary'])
        self.assertFalse(any(e['agent']=='coordinator' and 'Շարունակե՞լ' in e['message'] for e in r['events']))
    async def test_uncertain_and_unavailable_vision_stop(self):
        flow,rid,tools=await self.run_flow('largest blue',Scripted(task(selection='largest'),verdict='uncertain'))
        flow.approve(rid,True,True);await flow.execute(rid)
        flow.approve(rid,True,True);await flow.execute(rid)
        self.assertEqual(flow.get(rid)['state'],'awaiting_answer');self.assertEqual(len(tools.moves),2)
        class Unavailable(Scripted):
            async def check_vision(self):raise ValueError('Vision unavailable')
        flow,rid,tools=await self.run_flow('all blue',Unavailable())
        self.assertEqual(flow.get(rid)['state'],'failed');self.assertFalse(tools.moves)
    async def test_direct_move_no_camera_or_vision(self):
        flow,rid,tools=await self.run_flow('գնա 100 120 50',Scripted(task('move',coordinates=dict(x=100,y=120,z=50))))
        flow.approve(rid,True,True);await flow.execute(rid)
        self.assertEqual(tools.position,[100,120,50]);self.assertEqual(len(tools.moves),1)
    async def test_inspect_does_not_need_printer(self):
        flow,rid,tools=await self.run_flow('inspect')
        self.assertEqual(flow.get(rid)['state'],'observed');self.assertFalse(tools.moves)
    async def test_clarification_then_new_approval(self):
        agents=Scripted(task('ask'))
        flow,rid,tools=await self.run_flow('move somewhere',agents)
        self.assertEqual(flow.get(rid)['state'],'awaiting_answer')
        agents.task=task('move',coordinates=dict(x=1,y=2,z=100))
        flow.claim_answer(rid,'1 2 100');await flow.answer(rid)
        self.assertEqual(flow.get(rid)['state'],'awaiting_confirmation');self.assertFalse(tools.moves)
    async def test_stop_during_first_wipe_finishes_path_and_no_next(self):
        flow,rid,tools=await self.run_flow('all blue')
        original=tools.call
        async def call(server,name,args=None):
            result=await original(server,name,args)
            if name=='execute_sequence' and len(tools.moves)==2:flow.request_stop(rid)
            return result
        tools.call=call
        flow.approve(rid,True,True);await flow.execute(rid)
        flow.approve(rid,True,True);await flow.execute(rid)
        self.assertEqual(flow.get(rid)['state'],'stopped');self.assertEqual(len(tools.moves),2)
    async def test_expired_authorization_scope_change_and_uncertain_movement(self):
        for kind in ('expired','scope','failure'):
            flow,rid,tools=await self.run_flow('all blue');flow.approve(rid,True,True)
            if kind=='expired':flow.runs[rid]['authorization']['created']-=1801
            if kind=='scope':flow.runs[rid]['task']['color']='green'
            if kind=='failure':
                original=tools.call
                async def call(server,name,args=None):
                    if name=='execute_sequence':tools.moves.append('attempt');raise RuntimeError('uncertain')
                    return await original(server,name,args)
                tools.call=call
            await flow.execute(rid)
            self.assertEqual(flow.get(rid)['state'],'failed')
            self.assertEqual(len(tools.moves),1 if kind=='failure' else 0)
    async def test_calibration_and_stale_frame(self):
        flow,rid,_=await self.run_flow('all blue')
        scene=dict(calibration=dict(status='valid',calibration_id='a'),frame=dict(acquired_at=datetime.now(timezone.utc).isoformat()))
        flow.validate_frame(scene,'a',time.time()-1)
        with self.assertRaises(ValueError):flow.validate_frame(scene,'b',0)
        scene['frame']['acquired_at']=(datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat()
        with self.assertRaises(ValueError):flow.validate_frame(scene,'a',0)

class Boundaries(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_llm_id_never_wipes(self):
        class Bad(Scripted):
            async def decide(self,role,evidence,contract):
                if role=='selection':return dict(action='select',target_ids=['invented'],message='Bad ID')
                return await super().decide(role,evidence,contract)
        with tempfile.TemporaryDirectory() as tmp:
            tools=Printer();flow=Workflow(tools,Bad(),tmp,demo=True)
            rid=flow.new('all blue');await flow.prepare(rid);flow.approve(rid,True,True);await flow.execute(rid)
            self.assertEqual(flow.get(rid)['state'],'failed')
            self.assertEqual(len(tools.moves),1)  # Home only; never contact.
    async def test_too_many_targets_no_contact(self):
        from unittest.mock import patch
        many=synthetic_scene(1)['detections'][:1]*21
        many=[dict(copy.deepcopy(c),printer_coordinates_mm=dict(x=20+i*5,y=60)) for i,c in enumerate(many)]
        with tempfile.TemporaryDirectory() as tmp:
            tools=Printer();flow=Workflow(tools,Scripted(),tmp,demo=True)
            rid=flow.new('all blue');await flow.prepare(rid);flow.approve(rid,True,True)
            async def view(*args):return dict(cells=many,frame_id='s',frame_ids=['s'],calibration_id='synthetic')
            with patch.object(flow,'view',view):await flow.execute(rid)
            self.assertEqual(flow.get(rid)['state'],'failed');self.assertEqual(len(tools.moves),1)
    async def test_real_mode_cannot_use_synthetic_measurements(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            tools=Printer();flow=Workflow(tools,Scripted(),tmp,demo=True)
            rid=flow.new('all blue');await flow.prepare(rid);tools.mode='real'
            with patch.dict(os.environ,{'PRINTER_ALLOW_MOTION':'1'}):
                with self.assertRaises(ValueError):flow.approve(rid,True,True)
            self.assertFalse(tools.moves)
    async def test_missing_target_skip_keeps_original_queue(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            tools=Printer();flow=Workflow(tools,Scripted(),tmp,demo=True)
            rid=flow.new('all blue');await flow.prepare(rid);flow.approve(rid,True,True)
            original=flow.view;calls=0
            async def view(*args):
                nonlocal calls
                calls+=1
                if calls==2:raise ValueError('Target missing')
                return await original(*args)
            with patch.object(flow,'view',view):await flow.execute(rid)
            self.assertEqual(flow.get(rid)['state'],'awaiting_answer');self.assertEqual(len(tools.moves),1)
            ids=[c['target_id'] for c in flow.get(rid)['queue']]
            flow.claim_answer(rid,'Skip it and continue');await flow.answer(rid)
            self.assertEqual(flow.get(rid)['state'],'awaiting_confirmation')
            self.assertEqual(len(tools.moves),1)
            flow.approve(rid,True,True);await flow.execute(rid)
            r=flow.get(rid);self.assertEqual(r['state'],'completed')
            self.assertEqual([c['target_id'] for c in r['queue']],ids)
            self.assertEqual(r['results'][0]['verdict'],'skipped');self.assertEqual(len(tools.moves),2)

class API(unittest.TestCase):
    def test_headers_and_question_claim_and_stop(self):
        from app import create_app
        import asyncio
        class Runtime:
            def __init__(self,tmp):
                self.tools=Printer();self.workflow=Workflow(self.tools,Scripted(task('ask')),tmp,demo=True)
                self.pending=[]
            def submit(self,coro):self.pending.append(coro)
        with tempfile.TemporaryDirectory() as tmp:
            runtime=Runtime(tmp);client=create_app(runtime).test_client();headers={'X-Lab-Control':'local'}
            self.assertEqual(client.post('/api/prepare',json={'prompt':'x'}).status_code,403)
            rid=runtime.workflow.new('x');asyncio.run(runtime.workflow.prepare(rid))
            response=client.post(f'/api/runs/{rid}/answer',json={'answer':'blue'},headers=headers)
            self.assertEqual(response.status_code,202)
            self.assertEqual(client.post(f'/api/runs/{rid}/answer',json={'answer':'blue'},headers=headers).status_code,409)
            for coro in runtime.pending:coro.close()
            runtime.workflow.update(rid,state='awaiting_answer')
            self.assertEqual(client.post(f'/api/runs/{rid}/stop-task',json={},headers=headers).status_code,200)
            self.assertEqual(runtime.workflow.get(rid)['state'],'stopped')
