import copy
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from agents.contracts import selected_cells, validate_selection, validate_task
from agents.spatial import distance, spatial_evidence
from agents.workflow import Workflow
from agents.planning import HOME
from test_autonomous import Printer, Scripted, task
from test_status_speed import StatusPrinter


def nearest_task():
    return dict(task(selection='nearest'),reference=dict(color='green',selection='largest'))


def distance_task():
    return dict(task('inspect',None,None),distance_between=[dict(color=c,selection='largest') for c in ('blue','green')])


def cell(ident,color,x,y,area):
    return dict(target_id=ident,color=color,area_mm2=area,printer_coordinates_mm=dict(x=x,y=y))


class Geometry(unittest.TestCase):
    def test_xy_distance_and_scope_validation(self):
        cells=[cell('g','green',0,0,100),cell('b1','blue',3,4,80),cell('b2','blue',20,0,20)]
        self.assertEqual(distance(cells[0],cells[1]),5)
        self.assertEqual(selected_cells(cells,nearest_task())[0]['target_id'],'b1')
        evidence=spatial_evidence(cells,nearest_task(),'frame')
        self.assertEqual([e['distance_mm'] for e in evidence],[5,20])
        for ids in (['fake'],['g'],['b2'],['b1','b1']):
            with self.assertRaises(ValueError):validate_selection(dict(target_ids=ids),cells,nearest_task())
        cells[2]['printer_coordinates_mm']=dict(x=8,y=0)
        with self.assertRaisesRegex(ValueError,'3 mm'):selected_cells(cells,nearest_task())
        cells[2]['printer_coordinates_mm']=dict(x=8.01,y=0)
        self.assertEqual(selected_cells(cells,nearest_task())[0]['target_id'],'b1')

    def test_invalid_reference_missing_color_and_same_cell(self):
        for spec in ({},dict(color='red',selection='largest'),dict(color='green',selection='all')):
            with self.assertRaises(ValueError):validate_task(dict(nearest_task(),reference=spec))
        with self.assertRaises(ValueError):selected_cells([cell('b','blue',0,0,1)],nearest_task())
        spec=distance_task();spec['distance_between'][1]=spec['distance_between'][0]
        with self.assertRaises(ValueError):spatial_evidence([cell('b','blue',0,0,1)],spec,'f')
        with self.assertRaises(ValueError):validate_task(dict(nearest_task(),distance_between=distance_task()['distance_between']))
        with self.assertRaises(ValueError):distance(cell('a','blue',float('nan'),0,1),cell('b','green',1,2,1))


class SpatialWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_nearest_wipe_waits_for_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            printer=Printer();printer.position=HOME[:]
            flow=Workflow(printer,Scripted(nearest_task()),tmp,demo=True)
            rid=flow.new('Մաքրիր ամենամեծ կանաչին ամենամոտ կապույտը');await flow.prepare(rid)
            r=flow.get(rid)
            self.assertEqual(r['state'],'awaiting_confirmation',r.get('error'))
            self.assertEqual(r['phase'],'wipe');self.assertEqual(printer.moves,[])
            self.assertEqual(len(r['queue']),1);self.assertEqual(len(r['distances']),2)
            flow.approve(rid,True,True);await flow.execute(rid)
            self.assertEqual(flow.get(rid)['state'],'completed')
            self.assertEqual(len(printer.moves),1)

    async def test_distance_readonly_and_forged_endpoint(self):
        for invalid in (False,True):
            class Agent(Scripted):
                async def decide(self,role,evidence,contract):
                    if invalid and role=='selection':return dict(action='select',target_ids=['fake','other'],message='bad')
                    return await super().decide(role,evidence,contract)
            with tempfile.TemporaryDirectory() as tmp:
                printer=StatusPrinter();flow=Workflow(printer,Agent(distance_task()),tmp,demo=True)
                rid=flow.new('Distance between largest blue and green');await flow.prepare(rid)
                r=flow.get(rid)
                self.assertEqual(r['state'],'awaiting_answer' if invalid else 'observed',r.get('error'))
                self.assertEqual(printer.moves,[])
                if not invalid:self.assertAlmostEqual(r['distances'][0]['distance_mm'],67.0820393)

    async def test_home_then_inspect_has_separate_single_use_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            printer=StatusPrinter();flow=Workflow(printer,Scripted(dict(distance_task(),observe_from_home=True)),tmp,demo=True)
            rid=flow.new('Go home then measure');await flow.prepare(rid)
            self.assertEqual(flow.get(rid)['phase'],'observe_home');self.assertEqual(printer.moves,[])
            flow.approve(rid,True,True)
            with self.assertRaises(ValueError):flow.approve(rid,True,True)
            await flow.execute(rid)
            self.assertEqual(flow.get(rid)['state'],'observed');self.assertEqual(printer.moves,[HOME])

    async def test_bad_view_offers_home_once_and_stops_if_still_bad(self):
        with tempfile.TemporaryDirectory() as tmp:
            printer=StatusPrinter(offline=True);flow=Workflow(printer,Scripted(distance_task()),tmp)
            rid=flow.new('Measure distance');await flow.prepare(rid)
            self.assertEqual(flow.get(rid)['phase'],'observe_home');self.assertEqual(printer.moves,[])
            flow.approve(rid,True,True);await flow.execute(rid)
            self.assertEqual(flow.get(rid)['state'],'awaiting_answer')
            self.assertEqual(printer.moves,[HOME])

    async def test_near_tie_questions_without_plan(self):
        from agents.observation import synthetic_scene
        scene=synthetic_scene(1)
        scene['detections'][1]['printer_coordinates_mm']=dict(x=100,y=169)
        with tempfile.TemporaryDirectory() as tmp:
            printer=Printer();printer.position=HOME[:]
            class Choice(Scripted):
                async def decide(self,role,evidence,contract):
                    if role=='selection' and evidence.get('user_answer'):
                        return dict(action='select',target_ids=[evidence['inventory'][0]['target_id']],message='First option')
                    return await super().decide(role,evidence,contract)
            flow=Workflow(printer,Choice(nearest_task()),tmp,demo=True)
            with patch('agents.workflow.stationary_view',new=AsyncMock(return_value=dict(cells=scene['detections'],frame_id=scene['frame_id']))):
                rid=flow.new('Nearest');await flow.prepare(rid)
                self.assertEqual(printer.moves,[])
                self.assertNotIn('plan',flow.get(rid))
                self.assertEqual(flow.get(rid)['state'],'awaiting_answer')
                self.assertEqual(flow.get(rid)['question_context'],'spatial_choice')
                flow.claim_answer(rid,'Առաջինը');await flow.answer(rid)
                self.assertEqual(flow.get(rid)['state'],'awaiting_confirmation',flow.get(rid).get('error'))
                self.assertEqual(printer.moves,[])
