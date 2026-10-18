"""Fresh stationary single-view observations in printer XY coordinates."""
import asyncio
import copy
from datetime import datetime, timezone
import math
import statistics
from collections import Counter
import time
from uuid import uuid4




def point(cell):
    p=cell['printer_coordinates_mm']
    xy=[p['x'],p['y']]
    if any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in xy):
        raise ValueError('Invalid measured cell position')
    return xy


def candidates(scene):
    cells=[]
    for c in scene.get('detections',[]):
        if (c.get('calibration_status')=='valid' and c.get('printer_coordinates_mm')
                and c.get('color') in ('blue','green') and not c.get('touches_image_edge')):
            point(c)
            area=c.get('area_mm2')
            if isinstance(area,bool) or not isinstance(area,(float,int)) or not math.isfinite(area) or area<=0:
                raise ValueError('Invalid measured cell area')
            cells.append(c)
    return cells


def choose_blue(inventory):
    blue=sorted([c for c in inventory if c['color']=='blue'],key=lambda c:c['area_mm2'],reverse=True)
    if not blue or (len(blue)>1 and blue[0]['area_mm2']<=blue[1]['area_mm2']*1.05):
        raise ValueError('No unambiguous largest blue cell in the current view')
    return blue[0]


def stable_cells(scenes,tolerance):
    """Bound 80% of samples and the newest frame around the median, reject drift."""
    if len(scenes)<3: raise ValueError('At least three distinct frames are required')
    base=candidates(scenes[0]); tracks=[[c] for c in base]
    for scene in scenes[1:]:
        current=candidates(scene)
        if len(current)!=len(base): raise ValueError('Cell visibility changed during the stationary window')
        used=set()
        for track in tracks:
            center=[statistics.median(point(c)[i] for c in track) for i in (0,1)]
            nearby=[i for i,c in enumerate(current) if c['color']==track[0]['color'] and
                    math.dist(point(c),center)<=2*tolerance]
            if len(nearby)!=1 or nearby[0] in used:
                raise ValueError('Cell association is unstable or ambiguous')
            used.add(nearby[0]);track.append(current[nearby[0]])
    for track in tracks:
        positions=[point(c) for c in track]
        median=[statistics.median(p[i] for p in positions) for i in (0,1)]
        inliers=sum(math.dist(p,median)<=tolerance for p in positions)
        if inliers<max(3,math.ceil(len(track)*.8)) or math.dist(positions[-1],median)>tolerance:
            raise ValueError('Cell position exceeds the median stability tolerance')
        width=max(1,len(track)//3)
        early=[statistics.median(p[i] for p in positions[:width]) for i in (0,1)]
        late=[statistics.median(p[i] for p in positions[-width:]) for i in (0,1)]
        if math.dist(early,late)>tolerance:
            raise ValueError('Cell position drifts during the stationary window')
    # Preserve exact newest-frame measurements and their provenance, no fabricated center.
    return [copy.deepcopy(track[-1]) for track in tracks]


def stable_target(scenes, tolerance):
    """Stabilize the chosen largest blue target, not unrelated faint marks.

    Every frame must still have a unique largest blue cell and valid association.
    A new larger cell, a near tie, loss of the selected cell or target drift fails.
    Return the exact newest inventory only after its selected target is validated.
    """
    selected=[]
    for scene in scenes:
        target=choose_blue(candidates(scene))
        selected.append(dict(detections=[target]))
    stable_cells(selected,tolerance)
    return copy.deepcopy(candidates(scenes[-1]))


def synthetic_scene(index):
    """Scripted camera-free single-view fixture; no real measurement claims."""
    cells=[]
    for x,y,area,color in [(160.,130.,150.,'blue'), (50.,50.,40.,'blue'), (100.,100.,60.,'green')]:
        cells.append(dict(color=color,label='defective' if color=='blue' else 'healthy',
            printer_coordinates_mm=dict(x=x,y=y),area_mm2=area,calibration_status='valid',
            calibration_id='synthetic',frame_id=f'synthetic-view-{index}',center=dict(x=x,y=y)))
    return dict(frame_id=f'synthetic-view-{index}',calibration=dict(status='valid',calibration_id='synthetic'),detections=cells)


async def stationary_view(tools,window,calibration_id,after,demo_index=None,selector=None):
    if demo_index is not None:
        scene=synthetic_scene(demo_index)
        return dict(frame_id=scene['frame_id'],frame_ids=[scene['frame_id']],cells=scene['detections'],
                    calibration_id='synthetic',synthetic=True)
    stabilize = (lambda scenes,tolerance: stable_scope(scenes,tolerance,selector)) if selector else stable_target
    deadline=time.monotonic()+window['timeout_seconds']; seen=set();scenes=[]; began=None
    reasons=Counter()
    while time.monotonic()<deadline:
        scene=await tools.call('scanner','scanner_get_live_detections')
        calibration=scene.get('calibration') or {}
        if calibration.get('status')!='valid':
            scenes=[];began=None
            reasons['grid_'+str(calibration.get('status'))]+=1
            await asyncio.sleep(.15);continue
        if calibration.get('calibration_id')!=calibration_id:
            raise ValueError('Calibration changed during observation; stop and prepare again')
        acquired=datetime.fromisoformat(scene['frame']['acquired_at']).timestamp()
        if acquired<after or time.time()-acquired>2 or acquired>time.time()+1:
            reasons['stale_frame']+=1
            await asyncio.sleep(.15);continue
        if scene['frame_id'] in seen:
            reasons['duplicate_frame']+=1
            await asyncio.sleep(.1);continue
        seen.add(scene['frame_id'])
        if began is None: began=time.monotonic()
        scenes.append(scene)
        # Retain a sliding full-duration window rather than restarting on every outlier.
        while len(scenes)>3 and (datetime.fromisoformat(scenes[-1]['frame']['acquired_at']).timestamp()-
                datetime.fromisoformat(scenes[1]['frame']['acquired_at']).timestamp())>=window['stable_seconds']:
            scenes.pop(0)
        span=(datetime.fromisoformat(scenes[-1]['frame']['acquired_at']).timestamp()-
              datetime.fromisoformat(scenes[0]['frame']['acquired_at']).timestamp())
        try: cells=stabilize(scenes,window['tolerance_mm'])
        except ValueError as exc:
            reasons[str(exc)]+=1
            await asyncio.sleep(.1);continue
        if span>=window['stable_seconds']:
            # Save independent raw and annotated evidence at this stationary stop.
            saved=await tools.call('scanner','scanner_scan_current_frame')
            if (saved.get('calibration') or {}).get('calibration_id')!=calibration_id or (saved.get('calibration') or {}).get('status')!='valid':
                raise ValueError('Calibration lost while saving observation view')
            if datetime.fromisoformat(saved['frame']['acquired_at']).timestamp()<after:
                raise ValueError('Saved observation view is stale')
            acquired_saved=datetime.fromisoformat(saved['frame']['acquired_at']).timestamp()
            if time.time()-acquired_saved>2 or acquired_saved>time.time()+1:
                raise ValueError('Saved observation view is stale')
            cells=stabilize(scenes+[saved],window['tolerance_mm'])
            return dict(frame_id=saved['frame_id'],frame_ids=[s['frame_id'] for s in scenes]+[saved['frame_id']],
                        cells=cells,calibration_id=calibration_id,annotated_image=saved.get('annotated_image'),
                        raw_image=saved.get('frame',{}).get('raw_image'),result_json=saved.get('result_json'),
                        calibration=saved['calibration'], frame=saved['frame'],
                        stability_scope='selected_scope' if selector else 'largest_blue_target')
        await asyncio.sleep(.1)
    raise ValueError('Observation view did not stabilize before timeout; no automatic movement retry. Diagnostics: '+json_diagnostics(reasons))


def json_diagnostics(reasons):
    return '; '.join(f'{reason}: {count}' for reason,count in reasons.most_common()) or 'no usable frames'



def stable_scope(scenes, tolerance, selector):
    selected=[dict(detections=selector(candidates(scene))) for scene in scenes]
    stable_cells(selected,tolerance)
    return copy.deepcopy(candidates(scenes[-1]))
