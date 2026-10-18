"""Same-frame image provenance, crop pixels, and bounded image serving."""
import copy
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

from test_status_speed import StatusPrinter,AnswerAgent
from test_autonomous import task
from agents.workflow import Workflow


class GalleryWorker(unittest.TestCase):
    def test_exact_source_pixels_bounds_and_invalid_sources(self):
        root=Path(__file__).resolve().parents[2]
        code=r'''
import copy,sys,tempfile
from pathlib import Path
import cv2,numpy as np
sys.path.insert(0,str(Path.cwd()/'lab-agents'))
from agents.gallery import create_gallery
root=Path.cwd()/'shape-scanner/results/images'
with tempfile.TemporaryDirectory(dir=root) as tmp:
 p=Path(tmp);raw=np.full((240,360,3),250,np.uint8)
 raw[40:70,40:75]=(240,10,20);raw[130:175,200:250]=(5,200,10)
 cv2.imwrite(str(p/'raw.png'),raw)
 cells=[dict(detection_id='blue',frame_id='frame',color='blue',bbox=dict(x=40,y=40,width=35,height=30)),
        dict(detection_id='green',frame_id='frame',color='green',bbox=dict(x=200,y=130,width=50,height=45))]
 scene=dict(frame_id='frame',frame=dict(frame_id='frame',raw_image=str(p/'raw.png'),acquired_at='2026-10-17T10:00:00+00:00'),
            calibration=dict(board_polygon_px=[[20,20],[340,20],[340,220],[20,220]]),detections=cells)
 def create(scene,name):return create_gallery(dict(scene=scene,detection_ids=['green','blue'],output=str(p/name)))
 result=create(scene,'gallery')
 assert result['frame_id']=='frame' and result['board_crop_px']==[8,8,353,233]
 assert cv2.imread(result['board_image']).shape[:2]==(225,345)
 assert [c['display_number'] for c in result['cells']]==[1,2]
 for record in result['cells']:
  x0,y0,x1,y1=record['crop_bbox_px'];crop=cv2.imread(record['image'])
  assert np.array_equal(crop,raw[y0:y1,x0:x1]), 'Cell crop includes another frame or annotated pixels'
  assert record['frame_id']==result['frame_id']
 assert tuple(cv2.imread(result['cells'][0]['image'])[15,15])==(240,10,20)
 assert tuple(cv2.imread(result['cells'][1]['image'])[15,15])==(5,200,10)
 scene['detections'][0]['center']=dict(x=57,y=55)
 scene['detections'][1]['center']=dict(x=225,y=152)
 scene['distance_measurements']=[dict(frame_id='frame',from_detection_id='blue',to_detection_id='green',distance_mm=42.5)]
 linked=create(scene,'linked')
 assert not np.array_equal(cv2.imread(linked['board_image']),cv2.imread(result['board_image']))
 for a,b in zip(linked['cells'],result['cells']):
  assert np.array_equal(cv2.imread(a['image']),cv2.imread(b['image'])), 'Distance overlay leaked into crop'
 for kind in ('frame','duplicate','outside','bounds'):
  bad=copy.deepcopy(scene)
  if kind=='frame':bad['detections'][1]['frame_id']='other'
  if kind=='duplicate':bad['detections'][1]['detection_id']='blue'
  if kind=='outside':bad['frame']['raw_image']='/tmp/not-an-approved-frame.png'
  if kind=='bounds':bad['calibration']['board_polygon_px'][0]=[-10,20]
  try:create(bad,kind)
  except ValueError:pass
  else:raise AssertionError(kind+' was accepted')
 print('exact frame crops verified')
'''
        reply=subprocess.run([str(root/'shape-scanner/.venv/bin/python'),'-c',code],cwd=root,capture_output=True,text=True,timeout=30)
        self.assertEqual(reply.returncode,0,reply.stdout+reply.stderr)


class GalleryWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_one_saved_frame_drives_counts_rankings_and_image_ids(self):
        class Saved(StatusPrinter):
            async def call(self,server,name,args=None):
                result=await super().call(server,name,args)
                if name=='scanner_scan_current_frame':
                    result['frame_id']='saved'
                    for index,cell in enumerate(result['detections']):cell['detection_id']='id'+str(index)
                return result
        gallery=dict(frame_id='saved',board_image='board.png',cells=[
            dict(detection_id='id2',index=0,display_number=3),
            dict(detection_id='id0',index=1,display_number=1),
            dict(detection_id='id1',index=2,display_number=2)])
        with tempfile.TemporaryDirectory() as tmp:
            printer=Saved();flow=Workflow(printer,AnswerAgent(task('inspect')),tmp)
            with patch('agents.workflow.observation_gallery',new=AsyncMock(return_value=gallery)) as worker:
                rid=flow.new('How many cells?');await flow.prepare(rid)
            run=flow.get(rid)
            self.assertEqual(run['state'],'observed')
            self.assertEqual(run['observation_images']['frame_id'],run['observation']['frame_id'])
            self.assertEqual([(c['detection_id'],c['image_index']) for c in run['ranked_cells']],[('id0',1),('id1',2),('id2',0)])
            self.assertEqual(worker.call_args.args[0]['frame_id'],'saved')
            self.assertEqual(sum(name=='scanner_scan_current_frame' for name,_ in printer.calls),1)
            self.assertFalse(any(name=='scanner_get_live_detections' for name,_ in printer.calls))
            self.assertEqual(printer.moves,[])


class GalleryAPI(unittest.TestCase):
    def test_image_endpoints_reject_other_frames_paths_and_indices(self):
        from app import create_app,ROOT
        directory=ROOT/'results/observations';directory.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as tmp:
            board=Path(tmp)/'board.png';board.write_bytes(b'png fixture')
            record=dict(frame_id='frame',board_image=str(board),cells=[dict(index=0,frame_id='frame',image=str(board))])
            run=dict(observation_images=record,observation=dict(frame_id='frame'))
            flow=SimpleNamespace(demo=False,get=lambda rid:copy.deepcopy(run))
            app=create_app(SimpleNamespace(workflow=flow,tools=SimpleNamespace(mode='mock')))
            with app.test_client() as client:
                for suffix in ('board','cells/0'):
                    with client.get('/api/runs/test/observation/'+suffix) as response:
                        self.assertEqual(response.status_code,200);self.assertEqual(response.data,b'png fixture')
                self.assertEqual(client.get('/api/runs/test/observation/cells/9').status_code,409)
                # Cleaning clarification stores its saved frame in observation_view.
                run['observation_view']=run.pop('observation')
                for suffix in ('board','cells/0'):
                    with client.get('/api/runs/test/observation/'+suffix) as response:
                        self.assertEqual(response.status_code,200)
                run['observation_view']['frame_id']='wrong-frame'
                self.assertEqual(client.get('/api/runs/test/observation/board').status_code,409)
                run['observation_view']['frame_id']='frame'
                record['cells'][0]['frame_id']='other'
                self.assertEqual(client.get('/api/runs/test/observation/cells/0').status_code,409)
                record['board_image']='/tmp/not-allowed.png'
                self.assertEqual(client.get('/api/runs/test/observation/board').status_code,409)
                record['board_image']=str(board);record['frame_id']='different'
                self.assertEqual(client.get('/api/runs/test/observation/board').status_code,409)
