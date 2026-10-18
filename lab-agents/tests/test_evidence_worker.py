"""Run synthetic image checks in the existing scanner environment."""
import subprocess
from pathlib import Path
import unittest

class EvidenceWorker(unittest.TestCase):
    def test_aligned_ink_residue_occlusion_and_invalid_files(self):
        root=Path(__file__).resolve().parents[2]
        code=r'''
import sys,json,tempfile
from pathlib import Path
import cv2,numpy as np
sys.path.insert(0,str(Path.cwd()/'lab-agents'))
from agents.evidence import create_evidence
root=Path.cwd()/'shape-scanner/results/images'
with tempfile.TemporaryDirectory(dir=root) as tmp:
 p=Path(tmp);h=[[.25,0,0],[0,-.25,200],[0,0,1]]
 blank=np.full((800,800,3),255,np.uint8)
 original=blank.copy();cv2.circle(original,(400,400),22,(255,0,0),3)
 cv2.imwrite(str(p/'before.png'),original)
 target=dict(color='blue',printer_coordinates_mm=dict(x=109,y=108),bbox=dict(x=375,y=375,width=50,height=50))
 def view(name,frame,hmat=h):
  return dict(raw_image=str(p/name),frame_id=frame,calibration=dict(status='valid',calibration_id='c',printer_origin_mm=dict(x=9,y=8),image_to_board_homography=hmat))
 before=view('before.png','before')
 for kind,image in [('clean',blank),('residue',original),('occluded',np.zeros_like(blank))]:
  cv2.imwrite(str(p/(kind+'.png')),image)
  result=create_evidence(dict(target=target,before=before,after=view(kind+'.png',kind),output=str(p/kind)))
  if kind=='clean':assert result['remaining_fraction']==0 and result['evidence_usable']
  if kind=='residue':assert result['remaining_fraction']>.99
  if kind=='occluded':assert not result['evidence_usable']
 # Shift the physical image; the frame-specific homography must keep ROI identical.
 shifted=cv2.warpAffine(original,np.float32([[1,0,30],[0,1,10]]),(800,800),borderValue=(255,255,255))
 cv2.imwrite(str(p/'shift.png'),shifted)
 hshift=(np.array(h)@np.array([[1,0,-30],[0,1,-10],[0,0,1]])).tolist()
 result=create_evidence(dict(target=target,before=before,after=view('shift.png','shift',hshift),output=str(p/'shifted')))
 assert abs(result['remaining_fraction']-1)<.01
 bad=view('missing.png','bad')
 try:create_evidence(dict(target=target,before=before,after=bad,output=str(p/'bad')))
 except ValueError:pass
 else:raise AssertionError('Invalid image accepted')
 print('synthetic visual evidence passed')
'''
        result=subprocess.run([str(root/'shape-scanner/.venv/bin/python'),'-c',code],cwd=root,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
