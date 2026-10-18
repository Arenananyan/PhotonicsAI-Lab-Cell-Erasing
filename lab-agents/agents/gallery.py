"""Create a board overview and tight cell crops from one saved scanner frame.

Runs with the scanner Python so the dashboard needs no new imaging dependency.
"""
import json
import math
from pathlib import Path
import sys


def create_gallery(payload):
    import cv2
    import numpy as np
    scene=payload['scene'];frame=scene.get('frame') or {}
    if not scene.get('frame_id') or frame.get('frame_id',scene['frame_id'])!=scene['frame_id']:
        raise ValueError('Observation frame identifiers disagree')
    if not frame.get('raw_image'):raise ValueError('No saved observation image')
    allowed=Path(__file__).resolve().parents[2]/'shape-scanner/results/images'
    raw=Path(frame['raw_image']).resolve()
    if not raw.is_relative_to(allowed.resolve()):raise ValueError('Invalid observation image path')
    image=cv2.imread(str(raw))
    if image is None:raise ValueError('Saved observation image unavailable')
    height,width=image.shape[:2];annotated=image.copy();records=[];seen=set()
    selected=set(payload.get('detection_ids',[]))
    output=Path(payload['output']);output.mkdir(parents=True,exist_ok=False)
    polygon=(scene.get('calibration') or {}).get('board_polygon_px')
    bounds=[0,0,width,height]
    if polygon is not None:
        points=np.asarray(polygon,dtype=np.float64)
        if points.shape!=(4,2) or not np.isfinite(points).all():raise ValueError('Invalid board image bounds')
        # Preserve the camera view, including the entire calibrated quadrilateral.
        if np.any(points[:,0]<0) or np.any(points[:,0]>=width) or np.any(points[:,1]<0) or np.any(points[:,1]>=height):
            raise ValueError('The complete board is outside the captured image')
        margin=12
        bounds=[max(0,int(np.floor(points[:,0].min()))-margin),max(0,int(np.floor(points[:,1].min()))-margin),
                min(width,int(np.ceil(points[:,0].max()))+margin+1),min(height,int(np.ceil(points[:,1].max()))+margin+1)]
        cv2.polylines(annotated,[np.round(points).astype(np.int32)],True,(190,160,40),2)
    for number,cell in enumerate(scene.get('detections',[]),1):
        ident=cell.get('detection_id')
        if not ident:continue
        if ident in seen:raise ValueError('Duplicate observation detection ID')
        seen.add(ident)
        if cell.get('frame_id',scene['frame_id'])!=scene['frame_id']:
            raise ValueError('Cell image belongs to a different observation frame')
        bbox=cell.get('bbox') or {};values=[bbox.get(k) for k in ('x','y','width','height')]
        if any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) or int(v)!=v for v in values):continue
        x,y,w,h=map(int,values)
        if x<0 or y<0 or w<=0 or h<=0 or x+w>width or y+h>height:continue
        color=(210,100,35) if cell.get('color')=='blue' else (60,150,45)
        cv2.rectangle(annotated,(x,y),(x+w-1,y+h-1),color,2)
        text='#'+str(number);font_scale=max(.45,min(1.,width/1400))
        (tw,th),baseline=cv2.getTextSize(text,cv2.FONT_HERSHEY_SIMPLEX,font_scale,2)
        tx=max(0,min(x,width-tw-5));ty=max(th+4,y-5)
        cv2.rectangle(annotated,(tx,ty-th-3),(tx+tw+4,ty+baseline),color,-1)
        cv2.putText(annotated,text,(tx+2,ty),cv2.FONT_HERSHEY_SIMPLEX,font_scale,(255,255,255),2,cv2.LINE_AA)
        if ident not in selected:continue
        # Crop the original pixels, without labels or overlays from the overview.
        x0,y0,x1,y1=max(0,x-2),max(0,y-2),min(width,x+w+2),min(height,y+h+2)
        path=output/f'cell-{number}.png'
        if not cv2.imwrite(str(path),image[y0:y1,x0:x1]):raise ValueError('Cannot save cell image')
        records.append(dict(detection_id=ident,display_number=number,index=len(records),
                            image=str(path),crop_bbox_px=[x0,y0,x1,y1],frame_id=scene['frame_id']))
    by_id={c.get('detection_id'):c for c in scene.get('detections',[])}
    for measure in scene.get('distance_measurements',[]):
        if measure['frame_id']!=scene['frame_id']:raise ValueError('Distance image frame mismatch')
        endpoints=[]
        for key in ('from_detection_id','to_detection_id'):
            cell=by_id.get(measure[key],{});center=cell.get('center') or {}
            values=[center.get(axis) for axis in ('x','y')]
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
                raise ValueError('Measured cell image center unavailable')
            px,py=map(lambda v:int(round(v)),values)
            if not (0<=px<width and 0<=py<height):raise ValueError('Cell center outside image')
            endpoints.append((px,py))
        a,b=endpoints
        cv2.line(annotated,a,b,(20,120,240),3,cv2.LINE_AA)
        for p in endpoints:cv2.circle(annotated,p,7,(20,120,240),2)
        midpoint=((a[0]+b[0])//2,(a[1]+b[1])//2)
        cv2.putText(annotated,f"{measure['distance_mm']:.2f} mm",midpoint,cv2.FONT_HERSHEY_SIMPLEX,.7,(20,80,200),2,cv2.LINE_AA)
    x0,y0,x1,y1=bounds;board=output/'board.png'
    if not cv2.imwrite(str(board),annotated[y0:y1,x0:x1]):raise ValueError('Cannot save board image')
    return dict(frame_id=scene['frame_id'],acquired_at=frame.get('acquired_at'),board_image=str(board),
                board_crop_px=bounds,cells=records,source_raw_image=str(raw))


if __name__=='__main__':
    try:print(json.dumps(create_gallery(json.load(sys.stdin))))
    except Exception as exc:
        print(json.dumps({'error':str(exc)}));sys.exit(1)
