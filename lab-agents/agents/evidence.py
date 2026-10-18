"""Rectify fresh saved frames to the same physical board ROI; count actual ink pixels.

CLI runs with the scanner's Python, reusing its installed OpenCV/Numpy.
"""
import json
from pathlib import Path
import sys


def create_evidence(payload):
    import cv2
    import numpy as np
    target=payload['target']; output=Path(payload['output'])
    output.mkdir(parents=True,exist_ok=False)
    before,after=payload['before'],payload['after']
    scale=4.0
    origin=before['calibration']['printer_origin_mm']
    if origin!=after['calibration']['printer_origin_mm']:
        raise ValueError('Board origin changed')
    p=target['printer_coordinates_mm']
    cx,cy=p['x']-origin['x'],p['y']-origin['y']
    bbox=target.get('bbox')
    if not bbox: raise ValueError('Measured target bounds missing')
    h0=np.asarray(before['calibration']['image_to_board_homography'],np.float64)
    corners=np.float32([[[bbox['x'],bbox['y']],[bbox['x']+bbox['width'],bbox['y']],
                        [bbox['x']+bbox['width'],bbox['y']+bbox['height']],[bbox['x'],bbox['y']+bbox['height']]]])
    ext=cv2.perspectiveTransform(corners,h0)[0]
    radius=max(12.,float(np.max(np.abs(ext-[cx,cy])))+3.)
    x0,y0,x1,y1=cx-radius,cy-radius,cx+radius,cy+radius
    if min(x0,y0)<0 or max(x1,y1)>200:
        raise ValueError('The complete cleaning ROI must be visible inside the board')
    size=int(round(2*radius*scale))
    transform=np.array([[scale,0,-x0*scale],[0,-scale,y1*scale],[0,0,1]],np.float64)
    stats=[];paths=[];images=[]
    for index,view in enumerate((before,after)):
        if view['calibration']['status']!='valid' or view['calibration']['calibration_id']!=before['calibration']['calibration_id']:
            raise ValueError('Calibration changed during evidence capture')
        raw=Path(view['raw_image']).resolve()
        root=Path(__file__).resolve().parents[2]/'shape-scanner/results/images'
        if not raw.is_relative_to(root.resolve()): raise ValueError('Invalid scanner evidence path')
        image=cv2.imread(str(raw))
        if image is None: raise ValueError('Saved evidence image unavailable')
        h=np.asarray(view['calibration']['image_to_board_homography'],np.float64)
        if h.shape!=(3,3) or not np.isfinite(h).all(): raise ValueError('Invalid frame homography')
        warp=transform@h
        valid=cv2.warpPerspective(np.ones(image.shape[:2],np.uint8)*255,warp,(size,size),flags=cv2.INTER_NEAREST)
        if np.any(valid<255): raise ValueError('ROI is outside the captured frame')
        crop=cv2.warpPerspective(image,warp,(size,size))
        hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
        lo,hi=((90,65,40),(135,255,255)) if target['color']=='blue' else ((35,75,40),(88,255,255))
        # No filled contour: blank holes stay blank; small residual fragments count.
        mask=cv2.inRange(hsv,lo,hi)
        ink=float(np.count_nonzero(mask))/(scale*scale)
        stats.append(dict(colored_area_mm2=ink,dark_fraction=float(np.mean(hsv[:,:,2]<65)),
                          median_value=float(np.median(hsv[:,:,2]))))
        path=output/('before.png' if index==0 else 'after.png')
        if not cv2.imwrite(str(path),crop): raise ValueError('Cannot save aligned evidence')
        paths.append(str(path));images.append(crop)
    initial=stats[0]['colored_area_mm2']; remaining=stats[1]['colored_area_mm2']
    return dict(images=paths,before=stats[0],after=stats[1],roi_board_mm=[x0,y0,x1,y1],
                before_frame_id=before['frame_id'],after_frame_id=after['frame_id'],
                remaining_fraction=remaining/initial if initial else None,
                evidence_usable=initial>1 and stats[1]['dark_fraction']<.15 and
                    abs(stats[1]['median_value']-stats[0]['median_value'])<65,
                method='HSV colored-pixel count in frame-specific rectified board ROI; 4 pixels/mm')


if __name__=='__main__':
    try: print(json.dumps(create_evidence(json.load(sys.stdin))))
    except Exception as exc:
        print(json.dumps({'error':str(exc)}));sys.exit(1)
