import copy
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
from agents.workflow import Workflow
from agents.observation import synthetic_scene
from agents.contracts import selected_cells,AmbiguousSize
from test_autonomous import Printer,Scripted,task

class SizeChoice(unittest.IsolatedAsyncioTestCase):
    async def test_real_observation_attaches_candidate_crops(self):
        with tempfile.TemporaryDirectory() as directory:
            flow=Workflow(Printer(),Scripted(),directory,demo=False)
            rid=flow.new('Clean smallest green cell')
            flow.update(rid,task=task(color='green',selection='smallest'))
            source=copy.deepcopy(next(c for c in synthetic_scene(1)['detections'] if c['color']=='green'))
            cells=[dict(copy.deepcopy(source),area_mm2=area,detection_id=str(i)) for i,area in enumerate((90,94))]
            view=dict(cells=cells,frame_id='fixture',frame={'raw_image':'fixture.png'},calibration_id='synthetic')
            gallery=dict(frame_id='fixture',board_image='board.png',cells=[dict(detection_id=str(i),index=i,display_number=i+3) for i in range(2)])
            with patch.object(flow,'fresh_live',AsyncMock(return_value=synthetic_scene(1))),patch.object(flow,'view',AsyncMock(return_value=view)),patch('agents.workflow.observation_gallery',AsyncMock(return_value=gallery)) as build:
                await flow.recognize(rid)
            r=flow.get(rid)
            self.assertEqual(r['question_context'],'size_choice')
            self.assertEqual(r['observation_images'],gallery)
            self.assertEqual([c['image_index'] for c in r['ranked_cells']],[0,1])
            self.assertEqual(len(build.call_args.args[0]['detections']),2)

    async def test_close_sizes_offer_images_then_require_choice_and_path_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            tools=Printer();flow=Workflow(tools,Scripted(),directory,demo=True)
            rid=flow.new('Clean smallest green cell')
            flow.update(rid,task=task(color='green',selection='smallest'))
            source=copy.deepcopy(next(c for c in synthetic_scene(1)['detections'] if c['color']=='green'))
            cells=[dict(copy.deepcopy(source),area_mm2=area,detection_id=str(i),printer_coordinates_mm={'x':40+50*i,'y':80}) for i,area in enumerate((90,94))]
            view=AsyncMock(return_value=dict(cells=cells,frame_id='fixture',calibration_id='synthetic'))
            with patch.object(flow,'view',view):
                await flow.recognize(rid)
                r=flow.get(rid)
                self.assertEqual(r['question_context'],'size_choice')
                self.assertEqual(len(r['ranked_cells']),2)
                self.assertFalse(tools.moves)
                # Selector checks positions/colors without rejecting close areas.
                self.assertEqual(len(view.call_args.args[1](cells)),2)
                flow.claim_answer(rid,'3');await flow.answer(rid)
                self.assertEqual(flow.get(rid)['state'],'awaiting_answer')
                with patch.object(flow,'process_queue',AsyncMock()) as process:
                    flow.claim_answer(rid,'2');await flow.answer(rid)
                    self.assertEqual(flow.get(rid)['queue'][0]['area_mm2'],94)
                    self.assertIsNone(flow.get(rid)['authorization'])
                    process.assert_awaited_once()
                self.assertFalse(tools.moves)

    def test_all_never_requires_size_choice(self):
        cells=[dict(color='green',area_mm2=x) for x in (90,94)]
        self.assertEqual(selected_cells(cells,dict(color='green',selection='all')),cells)
        with self.assertRaises(AmbiguousSize):selected_cells(cells,dict(color='green',selection='smallest'))
