import copy
import tempfile
import unittest
from datetime import datetime,timezone
from test_autonomous import Printer,Scripted
from agents.workflow import Workflow
from agents.planning import HOME
from agents.observation import synthetic_scene

class PathApproval(unittest.IsolatedAsyncioTestCase):
    async def test_occluded_board_can_prepare_home_without_scanning(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        tool=Printer()
        original=tool.call
        async def call(server,name,args=None):
            if server=='scanner': raise RuntimeError('Board hidden by head')
            return await original(server,name,args)
        tool.call=call
        flow=Workflow(tool,Scripted(),tmp.name,demo=True)
        rid=flow.new('Clean largest blue')
        await flow.prepare(rid)
        run=flow.get(rid)
        self.assertEqual(run['state'],'awaiting_confirmation')
        self.assertEqual(run['phase'],'home')
        self.assertEqual(run['plan']['waypoints'][-1],HOME)
        self.assertFalse(tool.moves)

    async def setup_flow(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        tool=Printer();tool.position=HOME[:]
        flow=Workflow(tool,Scripted(),tmp.name,demo=True)
        rid=flow.new('Clean largest blue');await flow.prepare(rid)
        return flow,rid,tool

    async def test_at_home_recognizes_without_motion_then_executes_exact_plan(self):
        flow,rid,tool=await self.setup_flow();r=flow.get(rid)
        self.assertEqual(r['state'],'awaiting_confirmation')
        self.assertEqual(r['phase'],'wipe');self.assertFalse(tool.moves)
        self.assertEqual(r['plan']['target'],[160,130]);self.assertGreater(len(r['plan']['waypoints']),72)
        self.assertEqual(r['plan']['waypoints'][-1],HOME)
        expected=copy.deepcopy(r['plan'])
        flow.approve(rid,True,True);await flow.execute(rid)
        self.assertEqual(flow.get(rid)['state'],'completed')
        self.assertEqual(flow.get(rid)['results'][0]['plan'],expected)
        self.assertEqual(len(tool.moves),1)

    async def test_changed_pending_path_rejected(self):
        flow,rid,tool=await self.setup_flow()
        flow.approve(rid,True,True)
        flow.runs[rid]['pending_wipe']['plan']['waypoints'][0][0]+=5
        await flow.execute(rid)
        self.assertEqual(flow.get(rid)['state'],'failed');self.assertFalse(tool.moves)

    async def test_fresh_target_shift_after_approval_never_dispatches(self):
        flow,rid,tool=await self.setup_flow()
        flow.approve(rid,True,True);flow.demo=False
        original=tool.call
        async def call(server,name,args=None):
            if name=='scanner_get_live_detections':
                scene=synthetic_scene(1)
                scene['frame']={'acquired_at':datetime.now(timezone.utc).isoformat()}
                scene['detections'][0]['printer_coordinates_mm']['x']+=5
                return scene
            return await original(server,name,args)
        tool.call=call
        await flow.execute(rid)
        self.assertEqual(flow.get(rid)['state'],'failed');self.assertFalse(tool.moves)

    async def test_cancel_prepared_wipe_never_moves(self):
        flow,rid,tool=await self.setup_flow();flow.cancel(rid)
        with self.assertRaises(ValueError):flow.approve(rid,True,True)
        self.assertFalse(tool.moves)
