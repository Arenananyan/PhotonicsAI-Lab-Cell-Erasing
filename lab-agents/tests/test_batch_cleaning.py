import copy
import tempfile
import unittest
from unittest.mock import patch
from agents.workflow import Workflow
from agents.planning import HOME
from agents.observation import synthetic_scene
from test_autonomous import Printer, Scripted


class BatchCleaning(unittest.IsolatedAsyncioTestCase):
    async def setup_batch(self, agents=None):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        tools=Printer();tools.position=HOME[:]
        flow=Workflow(tools,agents or Scripted(verdict='residue'),tmp.name,demo=True)
        rid=flow.new('Clean all blue cells');await flow.prepare(rid)
        return flow,rid,tools

    async def test_four_targets_one_confirmation_despite_residue(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        tools=Printer();tools.position=HOME[:]
        flow=Workflow(tools,Scripted(verdict='residue'),tmp.name,demo=True)
        rid=flow.new('Clean all blue cells')
        source=synthetic_scene(1)['detections'][0]
        cells=[dict(copy.deepcopy(source),printer_coordinates_mm={'x':30+40*i,'y':80},detection_id=str(i)) for i in range(4)]
        async def view(_rid, selector):
            return dict(cells=selector(copy.deepcopy(cells)),frame_id='fixture',frame_ids=['fixture'],calibration_id='synthetic')
        with patch.object(flow,'view',view):
            await flow.prepare(rid)
            before=flow.get(rid)
            self.assertEqual(before['plan']['target_count'],4)
            self.assertEqual(len(before['plan']['waypoints']),sum(len(p['waypoints']) for p in before['batch_paths'].values()))
            self.assertFalse(tools.moves)
            flow.approve(rid,True,True);await flow.execute(rid)
        r=flow.get(rid)
        self.assertEqual(r['state'],'completed',r.get('error'))
        self.assertEqual(len(tools.moves),4)
        self.assertEqual(len(set(r['attempted'])),4)
        self.assertEqual([x['verdict'] for x in r['results']],['residue']*4)
        self.assertIn('4/4',r['summary'])
        self.assertEqual(sum(x['kind']=='operator_authorization' for x in r['audit']),1)
        self.assertFalse(any(x['kind']=='question' for x in r['audit']))
        self.assertEqual(tools.position,HOME)

    async def test_unusable_evidence_still_pauses_batch(self):
        class Unusable(Scripted):
            async def assess(self,evidence,images):
                evidence['evidence_usable']=False
                return {'verdict':'uncertain','message':'occluded'}
        flow,rid,tools=await self.setup_batch(Unusable())
        flow.approve(rid,True,True);await flow.execute(rid)
        self.assertEqual(flow.get(rid)['state'],'awaiting_answer')
        self.assertEqual(len(tools.moves),1)

    async def test_assessor_rate_limit_keeps_evidence_and_continues_batch(self):
        class RateLimited(Scripted):
            async def assess(self,evidence,images):
                raise RuntimeError('Vision model unavailable (429); evaluation is not success.')
        flow,rid,tools=await self.setup_batch(RateLimited())
        flow.approve(rid,True,True);await flow.execute(rid)
        r=flow.get(rid)
        self.assertEqual(r['state'],'completed',r.get('error'))
        self.assertEqual(len(tools.moves),len(r['queue']))
        self.assertEqual(len(set(r['attempted'])),len(r['queue']))
        self.assertTrue(all(x['verdict']=='uncertain' for x in r['results']))
        self.assertTrue(all(x['evidence']['evidence_usable'] for x in r['results']))
        self.assertFalse(any(x['kind']=='question' for x in r['audit']))

    async def test_assessor_failure_without_valid_measurement_still_pauses(self):
        for fraction in (None,float('nan'),float('inf'),True,-1):
            with self.subTest(fraction=fraction):
                class MissingMeasurement(Scripted):
                    async def assess(self,evidence,images):
                        evidence['remaining_fraction']=fraction
                        raise RuntimeError('Vision model unavailable (429)')
                flow,rid,tools=await self.setup_batch(MissingMeasurement())
                flow.approve(rid,True,True);await flow.execute(rid)
                self.assertEqual(flow.get(rid)['state'],'awaiting_answer')
                self.assertEqual(len(tools.moves),1)

    async def test_uncertain_execution_never_starts_next_target(self):
        flow,rid,tools=await self.setup_batch()
        original=tools.call
        async def fail(server,name,args=None):
            if name=='execute_sequence' and len(tools.moves)==1:
                raise RuntimeError('network outcome unknown')
            return await original(server,name,args)
        tools.call=fail
        flow.approve(rid,True,True);await flow.execute(rid)
        self.assertEqual(flow.get(rid)['state'],'failed')
        self.assertEqual(len(tools.moves),1)
        self.assertEqual(len(flow.get(rid)['results']),1)

    async def test_changed_batch_scope_never_dispatches(self):
        flow,rid,tools=await self.setup_batch()
        flow.approve(rid,True,True)
        flow.runs[rid]['queue'][1]['printer_coordinates_mm']['x']+=1
        await flow.execute(rid)
        self.assertEqual(flow.get(rid)['state'],'failed')
        self.assertFalse(tools.moves)

    async def test_changed_future_draft_cannot_change_authorized_path(self):
        flow,rid,tools=await self.setup_batch()
        flow.approve(rid,True,True)
        frozen=copy.deepcopy(flow.get(rid)['authorization']['batch_paths'])
        second=flow.get(rid)['queue'][1]['target_id']
        flow.runs[rid]['batch_paths'][second]['waypoints'][0][0]+=10
        await flow.execute(rid)
        r=flow.get(rid)
        self.assertEqual(r['state'],'completed')
        self.assertEqual(r['results'][1]['plan'],frozen[second])
