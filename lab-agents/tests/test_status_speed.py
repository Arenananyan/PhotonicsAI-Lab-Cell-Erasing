import copy
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from agents.contracts import validate_task
from agents.workflow import Workflow
from agents.observation import synthetic_scene
from test_autonomous import Printer,Scripted,task

class StatusPrinter(Printer):
    def __init__(self,stale=False,offline=False):
        super().__init__();self.calls=[];self.stale=stale;self.offline=offline
    async def call(self,server,name,args=None):
        self.calls.append((name,args))
        if server=='scanner':
            if self.offline:raise ValueError('Camera unavailable')
            if name=='scanner_scan_current_frame':
                scene=synthetic_scene(1)
                scene['frame']={'acquired_at':(datetime.now(timezone.utc)-timedelta(seconds=30 if self.stale else 0)).isoformat()}
                return scene
            return {'connected':True}
        return await super().call(server,name,args)

class AnswerAgent(Scripted):
    async def decide(self,role,evidence,contract):
        if role=='status_answer':
            self.evidence=evidence['evidence']
            return {'message':'Measured status answer'}
        return await super().decide(role,evidence,contract)

class StatusSpeedTests(unittest.IsolatedAsyncioTestCase):
    async def test_readonly_status_and_unavailable_camera(self):
        for stale,offline in ((False,False),(True,False),(False,True)):
            with tempfile.TemporaryDirectory() as tmp:
                printer=StatusPrinter(stale,offline);agent=AnswerAgent(task('inspect'))
                flow=Workflow(printer,agent,tmp);rid=flow.new('Where are you and how many blue cells?')
                await flow.prepare(rid);run=flow.get(rid)
                self.assertEqual(run['state'],'observed',run)
                self.assertEqual(run['answer_message'],'Measured status answer')
                obs=agent.evidence['observation']
                self.assertEqual(obs['available'],not(stale or offline))
                if obs['available']:self.assertEqual(obs['counts'],{'blue':2,'green':1})
                else:self.assertNotIn('counts',obs)
                self.assertTrue(agent.evidence['position']['available'])
                self.assertFalse(printer.moves)
                self.assertFalse(any(n.startswith('preview') or n=='execute_sequence' for n,a in printer.calls))

    async def test_task_speed_all_previews_and_default_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            printer=StatusPrinter();agent=Scripted(dict(task(),speed_mm_s=10))
            flow=Workflow(printer,agent,tmp,demo=True)
            rid=flow.new('Clean all blue at 10 mm/s');await flow.prepare(rid)
            self.assertEqual(flow.get(rid)['plan']['speed_mm_s'],10)
            for _ in range(2):
                flow.approve(rid,True,True);await flow.execute(rid)
            self.assertEqual(flow.get(rid)['state'],'completed',flow.get(rid).get('error'))
            previews=[a for n,a in printer.calls if n=='preview_sequence']
            self.assertEqual(len(previews),4)
            for args in previews:
                self.assertEqual(args['speed_mm_s'],10);self.assertEqual(args['z_speed_mm_s'],10)
            agent.task=task('move',coordinates=dict(x=30,y=50,z=60))
            rid=flow.new('Move');await flow.prepare(rid)
            self.assertEqual(flow.get(rid)['limits']['speed_mm_s'],20)
            flow.approve(rid,True,True)
            flow.runs[rid]['limits']['speed_mm_s']=15
            with self.assertRaises(ValueError):flow.guard(rid)

    def test_invalid_speeds(self):
        for speed in (0,-1,31,True,'10',float('nan'),float('inf')):
            with self.assertRaises(ValueError):validate_task(dict(task(),speed_mm_s=speed))

    async def test_uncalibrated_board_is_not_zero_cells(self):
        class LostBoard(StatusPrinter):
            async def call(self,server,name,args=None):
                value=await super().call(server,name,args)
                if name=='scanner_scan_current_frame':
                    value['detections']=[]
                    value['calibration']={'status':'border_not_found','detections_available':False}
                return value
        with tempfile.TemporaryDirectory() as tmp:
            printer=LostBoard();agent=AnswerAgent(task('inspect'));flow=Workflow(printer,agent,tmp)
            rid=flow.new('How many cells?');await flow.prepare(rid)
            obs=agent.evidence['observation']
            self.assertFalse(obs['available']);self.assertNotIn('counts',obs)
            self.assertFalse(printer.moves)

    async def test_llm_unavailable_preserves_actual_counts_without_motion(self):
        class Unavailable(AnswerAgent):
            async def decide(self,role,evidence,contract):
                if role=='status_answer':raise RuntimeError('429')
                return await super().decide(role,evidence,contract)
        with tempfile.TemporaryDirectory() as tmp:
            printer=StatusPrinter();flow=Workflow(printer,Unavailable(task('inspect')),tmp)
            rid=flow.new('Count cells');await flow.prepare(rid);r=flow.get(rid)
            self.assertEqual(r['state'],'observed')
            self.assertEqual(r['answer_warning'],'429')
            self.assertIn('Կապույտ՝ 2, կանաչ՝ 1, ընդհանուր՝ 3',r['answer_message'])
            self.assertFalse(printer.moves)
