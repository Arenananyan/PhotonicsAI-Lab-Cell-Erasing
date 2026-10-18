import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, patch
from agents.observation import choose_blue, stable_cells, stationary_view, synthetic_scene


class ObservationSelection(unittest.TestCase):
    def test_largest_blue_and_missing_or_ambiguous_blue(self):
        cells=synthetic_scene(1)['detections']
        self.assertEqual(choose_blue(cells)['printer_coordinates_mm'],dict(x=160,y=130))
        with self.assertRaises(ValueError): choose_blue([])
        cells[1]['area_mm2']=149
        with self.assertRaises(ValueError): choose_blue(cells)

    def test_stable_window_and_jitter_rejection(self):
        scenes=[synthetic_scene(1) for _ in range(3)]
        self.assertEqual(len(stable_cells(scenes,1)),3)
        scenes[-1]['detections'][0]['printer_coordinates_mm']['x']+=2
        with self.assertRaises(ValueError): stable_cells(scenes,1)
        with self.assertRaises(ValueError): stable_cells(scenes[:2],1)


class SurveyCameraFailures(unittest.IsolatedAsyncioTestCase):
    async def test_camera_failure_propagates_without_motion(self):
        tools=AsyncMock();tools.call.side_effect=RuntimeError('Camera unavailable')
        with self.assertRaisesRegex(RuntimeError,'Camera unavailable'):
            await stationary_view(tools,dict(timeout_seconds=1,stable_seconds=.5,tolerance_mm=1),'cal',0)
        self.assertEqual(tools.call.await_args.args[:2],('scanner','scanner_get_live_detections'))

    async def test_changed_calibration_rejects(self):
        tools=AsyncMock();tools.call.return_value=synthetic_scene(1)
        with self.assertRaisesRegex(ValueError,'Calibration changed'):
            await stationary_view(tools,dict(timeout_seconds=1),'different-calibration',0)

    async def test_stale_frames_cannot_satisfy_window(self):
        tools=AsyncMock();scene=synthetic_scene(1)
        scene['frame']=dict(acquired_at='2026-01-01T00:00:00+00:00')
        tools.call.return_value=scene
        with patch('agents.observation.time.monotonic',side_effect=[0,0,2]), patch('agents.observation.asyncio.sleep',new=AsyncMock()):
            with self.assertRaisesRegex(ValueError,'did not stabilize'):
                await stationary_view(tools,dict(timeout_seconds=1),'synthetic',datetime.now(timezone.utc).timestamp())
        self.assertEqual(tools.call.await_count,1)


class MedianStability(unittest.TestCase):
    def samples(self,offsets):
        scenes=[]
        for offset in offsets:
            scene=synthetic_scene(1)
            for cell in scene['detections']:
                cell['printer_coordinates_mm']['x']+=offset
            scenes.append(scene)
        return scenes

    def test_noise_with_pairwise_spread_above_tolerance(self):
        scene=self.samples([-.6,.6,0,-.4,.4,0,.1])
        cells=stable_cells(scene,1)
        self.assertEqual(cells,scene[-1]['detections'])

    def test_one_outlier_preserves_exact_last_frame(self):
        scenes=self.samples([0,0,1.7,0,0])
        self.assertEqual(stable_cells(scenes,1),scenes[-1]['detections'])

    def test_latest_outlier_cannot_be_used(self):
        with self.assertRaises(ValueError): stable_cells(self.samples([0,0,0,0,1.7]),1)

    def test_actual_drift_is_rejected_even_inside_median_radius(self):
        with self.assertRaisesRegex(ValueError,'drifts'):
            stable_cells(self.samples([0,.1,.3,.6,.9,1.2,1.4,1.5,1.5]),1)

    def test_too_many_outliers_are_rejected(self):
        with self.assertRaises(ValueError): stable_cells(self.samples([0,0,1.7,1.7,0]),1)


class SelectedTargetStability(unittest.TestCase):
    def test_unrelated_visibility_changes_do_not_reset_target(self):
        from agents.observation import stable_target
        scenes=[synthetic_scene(i) for i in range(5)]
        scenes[1]['detections'].pop()  # Faint healthy mark disappears.
        scenes[3]['detections'].pop(1)  # Smaller blue mark disappears.
        self.assertEqual(stable_target(scenes,1),scenes[-1]['detections'])

    def test_selected_target_drift_or_loss_is_rejected(self):
        from agents.observation import stable_target
        scenes=[synthetic_scene(i) for i in range(3)]
        scenes[-1]['detections'][0]['printer_coordinates_mm']['x']+=2
        with self.assertRaises(ValueError): stable_target(scenes,1)
        scenes[-1]['detections'].pop(0)
        with self.assertRaises(ValueError): stable_target(scenes,1)

    def test_competitor_near_tie_or_new_larger_cell_is_rejected(self):
        from agents.observation import stable_target
        for area in (149,200):
            scenes=[synthetic_scene(i) for i in range(3)]
            scenes[-1]['detections'][1]['area_mm2']=area
            with self.assertRaises(ValueError): stable_target(scenes,1)


class StationaryTargetWindow(unittest.IsolatedAsyncioTestCase):
    async def test_success_with_fresh_frames_and_unrelated_flicker(self):
        base=datetime.now(timezone.utc).timestamp()
        clock=[0.]
        scenes=[]
        for i,offset in enumerate((0,.7,1.4,2.1,2.3)):
            scene=synthetic_scene(i)
            scene['frame']=dict(acquired_at=datetime.fromtimestamp(base+offset,timezone.utc).isoformat())
            if i%2: scene['detections'].pop()  # Healthy mark flickers.
            scenes.append((offset,scene))
        tools=AsyncMock()
        async def call(server,name):
            offset,scene=scenes.pop(0)
            clock[0]=offset+.05
            if name=='scanner_scan_current_frame':
                self.assertEqual(offset,2.3)
            return scene
        tools.call.side_effect=call
        with patch('agents.observation.time.time',side_effect=lambda:base+clock[0]), \
             patch('agents.observation.time.monotonic',side_effect=lambda:clock[0]), \
             patch('agents.observation.asyncio.sleep',new=AsyncMock()):
            view=await stationary_view(tools,dict(timeout_seconds=10,stable_seconds=2,tolerance_mm=1),
                'synthetic',after=base-.01)
        self.assertEqual(view['stability_scope'],'largest_blue_target')
        self.assertEqual(len(view['frame_ids']),5)
        self.assertEqual(choose_blue(view['cells'])['frame_id'],'synthetic-view-4')
        self.assertFalse(scenes)

class FreshPreparation(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_new_frame_without_moving(self):
        import tempfile
        from agents.workflow import Workflow
        with tempfile.TemporaryDirectory() as tmp:
            tools=AsyncMock();tools.mode='mock'
            old=synthetic_scene(1);old['frame']={'acquired_at':'2026-01-01T00:00:00+00:00'}
            fresh=synthetic_scene(2);fresh['frame']={'acquired_at':datetime.now(timezone.utc).isoformat()}
            tools.call.side_effect=[old,fresh]
            flow=Workflow(tools,None,tmp);rid=flow.new('Clean')
            with patch('agents.workflow.asyncio.sleep',new=AsyncMock()):
                self.assertEqual(await flow.fresh_live(rid),fresh)
            self.assertEqual(tools.call.await_count,2)
            self.assertTrue(all(c.args[1]=='scanner_get_live_detections' for c in tools.call.await_args_list))

    async def test_old_frame_still_rejected_after_deadline(self):
        import tempfile
        from agents.workflow import Workflow
        with tempfile.TemporaryDirectory() as tmp:
            tools=AsyncMock();tools.mode='mock'
            scene=synthetic_scene(1);scene['frame']={'acquired_at':'2026-01-01T00:00:00+00:00'}
            tools.call.return_value=scene
            flow=Workflow(tools,None,tmp);rid=flow.new('Clean')
            with self.assertRaisesRegex(ValueError,'Stale camera frame'):
                await flow.fresh_live(rid,timeout=0)
