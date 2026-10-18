import asyncio
import tempfile
from pathlib import Path
import unittest
from agents.planning import make_plan, make_home_plan
from agents.workflow import Workflow
from agents.llm import GroqAgents
from agents.tools import Tools


class PlanTests(unittest.TestCase):
    def test_circle_geometry_clearance_and_return_home(self):
        import math
        p=make_plan([0,0,20],{'x':160,'y':130})
        low=[v for v in p['waypoints'] if v[2]==14.5]
        self.assertEqual(low[0],[160,130,14.5])
        self.assertEqual(low[1],[160,140,14.5])
        self.assertEqual(low[-1],low[1])
        self.assertEqual(len(low),74)
        ring=low[1:]
        for v in ring:
            self.assertAlmostEqual(math.hypot(v[0]-160,v[1]-130),10,delta=.001)
        signed=sum((a[0]-160)*(b[1]-130)-(b[0]-160)*(a[1]-130)
                   for a,b in zip(ring,ring[1:]))
        self.assertLess(signed,0)  # Clockwise in printer XY.
        current=p['start'][:]
        reconstructed=[]
        for step in p['steps']:
            if step['axis']=='xy':
                self.assertEqual(current[2],14.5)
                current[:2]=[round(a+b,3) for a,b in zip(current[:2],step['distance_mm'])]
            else:
                i='xyz'.index(step['axis'])
                if i<2 and current[2]!=100:
                    self.assertEqual((step['axis'],step['distance_mm']),('y',10))
                current[i]=round(current[i]+step['distance_mm'],3)
            reconstructed.append(current[:])
        self.assertEqual(reconstructed,p['waypoints'])
        self.assertEqual(current,[209,208,100])
        self.assertEqual(p['speed_mm_s'],20)

    def test_home_lifts_before_xy_and_is_noop_when_already_home(self):
        plan=make_home_plan([50,60,14.5])
        self.assertEqual(plan['waypoints'],[[50,60,100],[209,60,100],[209,208,100]])
        self.assertEqual([step['axis'] for step in plan['steps']],['z','x','y'])
        self.assertEqual(make_home_plan([209,208,100])['steps'],[])
        for bad in ([True,0,0],[0,0,float('nan')],[0,0]):
            with self.assertRaises(ValueError): make_home_plan(bad)

    def test_reject_invalid_coordinates(self):
        for x in (True,float('nan'),float('inf')):
            with self.assertRaises(ValueError): make_plan([0,0,20],{'x':x,'y':10})


class Integration(unittest.IsolatedAsyncioTestCase):
    async def test_actual_mcp_demo_full_plan_single_use(self):
        tools=await Tools('mock').open()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                flow=Workflow(tools,GroqAgents(demo=True),Path(tmp),demo=True)
                rid=flow.new('Visit largest blue')
                await flow.prepare(rid)
                r=flow.get(rid)
                self.assertEqual(r['state'],'awaiting_confirmation',r)
                self.assertFalse(r['motion_sent'])
                with self.assertRaises(ValueError): flow.approve(rid,True,False)
                flow.approve(rid,True,True)
                with self.assertRaises(ValueError): flow.approve(rid,True,True)
                await flow.execute(rid)
                self.assertEqual(flow.get(rid)['state'],'awaiting_confirmation')
                self.assertEqual(flow.get(rid)['phase'],'wipe')
                self.assertEqual(flow.get(rid)['results'],[])
                flow.approve(rid,True,True);await flow.execute(rid)
                r=flow.get(rid)
                self.assertEqual(r['state'],'completed',r)
                self.assertEqual(len(r['inventory']),3)
                self.assertEqual(r['target']['printer_coordinates_mm'],dict(x=160,y=130))
                self.assertEqual(r['home_execution']['reported_position'],[209,208,100])
                self.assertTrue(r['verification']['returned_home'])
                self.assertEqual(r['verification']['position_mm'],dict(x=209,y=208,z=100))
                self.assertEqual(r['results'][0]['verdict'],'clean')
                self.assertTrue((Path(tmp)/(rid+'.json')).is_file())
                rid2=flow.new('Next run');await flow.prepare(rid2)
                self.assertTrue(flow.get(rid2)['plan']['steps'])
                self.assertEqual(flow.get(rid2)['phase'],'wipe')
                flow.cancel(rid2)
        finally: await tools.close()

    async def test_llm_failure_never_dispatches(self):
        class Failing:
            async def decide(self,*args): raise RuntimeError('Unavailable LLM')
        tools=type('Tools',(),{'mode':'mock'})()
        with tempfile.TemporaryDirectory() as tmp:
            flow=Workflow(tools,Failing(),Path(tmp))
            rid=flow.new('Visit');await flow.prepare(rid)
            self.assertEqual(flow.get(rid)['state'],'failed')
            self.assertFalse(flow.get(rid)['motion_sent'])

class WorkflowFailures(unittest.IsolatedAsyncioTestCase):
    async def test_expired_preview_and_cancel(self):
        import time
        class Tool:
            mode='mock'
            async def call(self,server,name,args=None):
                if name=='printer_status': return dict(state={'webhooks':{'state':'ready'}})
                if name=='printer_command': return dict(simulated=True,data={'position_mm':dict(x=209,y=208,z=100)})
                return dict(start=[209,208,100],token='token',simulated=True)
        with tempfile.TemporaryDirectory() as tmp:
            flow=Workflow(Tool(),GroqAgents(demo=True),tmp,demo=True)
            rid=flow.new('visit');await flow.prepare(rid)
            flow.update(rid,preview_monotonic=time.monotonic()-111)
            with self.assertRaises(ValueError): flow.approve(rid,True,True)
            flow.cancel(rid)
            self.assertEqual(flow.get(rid)['state'],'cancelled')
            with self.assertRaises(ValueError): flow.approve(rid,True,True)

    async def test_failed_execution_not_retried(self):
        class Tool:
            mode='mock'
            calls=0
            async def call(self,server,name,args=None):
                if name=='printer_status': return dict(state={'webhooks':{'state':'ready'}})
                if name=='printer_command': return dict(simulated=True,data={'position_mm':dict(x=209,y=208,z=100)})
                if name=='execute_sequence':
                    self.calls+=1
                    raise RuntimeError('Uncertain execution')
                return dict(start=[209,208,100],token='token',simulated=True)
        tool=Tool()
        with tempfile.TemporaryDirectory() as tmp:
            flow=Workflow(tool,GroqAgents(demo=True),tmp,demo=True)
            rid=flow.new('visit');await flow.prepare(rid)
            flow.approve(rid,True,True);await flow.execute(rid)
            self.assertEqual(flow.get(rid)['state'],'failed')
            self.assertEqual(tool.calls,1)
            with self.assertRaises(ValueError): flow.approve(rid,True,True)


class MockResetTests(unittest.TestCase):
    def test_stop_reset_and_real_mode_block(self):
        from app import Runtime, create_app
        runtime=Runtime('mock',True)
        try:
            client=create_app(runtime).test_client()
            self.assertIn('data-home="209, 208, 100"', client.get('/').get_data(as_text=True))
            headers={'X-Lab-Control':'local'}
            self.assertEqual(client.post('/api/stop',json={'confirmed':True},headers=headers).status_code,200)
            flow=runtime.workflow
            rid=flow.new('visit')
            runtime.submit(flow.prepare(rid)).result(timeout=10)
            self.assertEqual(flow.get(rid)['state'],'failed')
            self.assertIn('Վերականգնել',flow.get(rid)['error'])
            self.assertEqual(client.post('/api/simulation/reset',json={},headers=headers).status_code,200)
            status=runtime.submit(runtime.tools.call('printer','printer_status')).result(timeout=5)
            self.assertEqual(status['state']['webhooks']['state'],'ready')
            runtime.tools.mode='real'
            self.assertEqual(client.post('/api/simulation/reset',json={},headers=headers).status_code,409)
            runtime.tools.mode='mock'
        finally: runtime.close()


class ObservationDispatchFailures(unittest.IsolatedAsyncioTestCase):
    async def test_camera_loss_after_first_stop_prevents_further_moves(self):
        tools=await Tools('mock').open()
        original=tools.call
        movements=[]
        async def fail_camera(server,name,args=None):
            if server=='scanner': raise RuntimeError('Camera unavailable at home')
            if name=='execute_sequence': movements.append(name)
            return await original(server,name,args)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                flow=Workflow(tools,GroqAgents(demo=True),tmp,demo=True)
                rid=flow.new('visit');await flow.prepare(rid)
                flow.approve(rid,True,True)
                flow.demo=False
                tools.call=fail_camera
                await flow.execute(rid)
                r=flow.get(rid)
                self.assertEqual(r['state'],'failed')
                self.assertIn('Camera unavailable',r['error'])
                self.assertEqual(len(movements),1)
                self.assertNotIn('target',r)
        finally: await tools.close()
