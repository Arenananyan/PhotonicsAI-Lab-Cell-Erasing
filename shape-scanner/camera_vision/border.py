"""Locate a complete dark marker outline; no stale map or physical-size inference."""
from itertools import combinations
import cv2
import numpy as np

BOARD = np.float32([[0,0],[200,0],[200,200],[0,200]])


def order_corners(points):
    q=np.asarray(points,np.float32).reshape(4,2)
    sums=q.sum(axis=1);differences=q[:,0]-q[:,1]
    indices=[int(differences.argmin()),int(sums.argmax()),int(differences.argmax()),int(sums.argmin())]
    if len(set(indices))!=4: return None
    return q[indices]


def fit_side(gray,a,b):
    """Find the center of a bounded ink stripe near the proposed side."""
    delta=b-a;length=float(np.linalg.norm(delta))
    if length<60: return None
    normal=np.float32([-delta[1],delta[0]])/length
    offsets=np.arange(-18,18.01,.5,dtype=np.float32)
    base=a[None,:]+np.linspace(.06,.94,90,dtype=np.float32)[:,None]*delta
    xy=base[:,None,:]+offsets[None,:,None]*normal
    if ((xy[:,:,0]<1).any() or (xy[:,:,0]>=gray.shape[1]-1).any() or
        (xy[:,:,1]<1).any() or (xy[:,:,1]>=gray.shape[0]-1).any()): return None
    profiles=cv2.remap(gray,xy[:,:,0],xy[:,:,1],cv2.INTER_LINEAR).astype(float)
    # Evaluate all contiguous ink runs together. This preserves the original
    # per-profile tests while avoiding thousands of Python/Numpy calls per quad.
    cutoffs=np.minimum(165,np.percentile(profiles,85,axis=1)-30)
    ink=profiles<cutoffs[:,None]
    edges=np.diff(np.pad(ink.astype(np.int8),((0,0),(1,1))),axis=1)
    rows,starts=np.nonzero(edges==1)
    end_rows,ends=np.nonzero(edges==-1)  # exclusive endpoints, same row/run order
    lengths=ends-starts
    valid=(lengths>=3)&(lengths<=26)&(starts>=2)&(ends<=len(offsets)-2)
    rows,starts,ends,lengths=(v[valid] for v in (rows,starts,ends,lengths))
    if not len(rows): return None
    weights=cutoffs[:,None]-profiles
    sums=np.pad(np.cumsum(weights,axis=1),((0,0),(1,0)))
    moments=np.pad(np.cumsum(weights*offsets,axis=1),((0,0),(1,0)))
    shifts=(moments[rows,ends]-moments[rows,starts])/(sums[rows,ends]-sums[rows,starts])
    left=np.maximum.accumulate(profiles,axis=1)[rows,starts-1]
    right=np.maximum.accumulate(profiles[:,::-1],axis=1)[:,::-1][rows,ends]
    # Each candidate has at most 26 samples; masked gather computes its minimum.
    positions=starts[:,None]+np.arange(26)[None,:]
    values=profiles[rows[:,None],np.minimum(positions,len(offsets)-1)]
    minima=np.min(np.where(positions<ends[:,None],values,np.inf),axis=1)
    valid=np.minimum(left,right)-minima>=30
    rows,shifts,lengths=(v[valid] for v in (rows,shifts,lengths))
    if not len(rows): return None
    order=np.lexsort((lengths,shifts,np.abs(shifts),rows))
    rows,shifts,lengths=(v[order] for v in (rows,shifts,lengths))
    first=np.r_[True,rows[1:]!=rows[:-1]]
    rows,shifts,lengths=(v[first] for v in (rows,shifts,lengths))
    found=base[rows]+shifts[:,None]*normal
    widths=lengths*.5
    support=len(found)/len(base)
    if support<.65: return None
    points=np.float32(found)
    line=cv2.fitLine(points,cv2.DIST_HUBER,0,.01,.01).ravel()
    direction=line[:2];origin=line[2:]
    residual=np.abs(direction[0]*(points[:,1]-origin[1])-direction[1]*(points[:,0]-origin[0]))
    keep=residual<=2.5
    if keep.sum()<.65*len(base): return None
    line=cv2.fitLine(points[keep],cv2.DIST_HUBER,0,.01,.01).ravel()
    return line,round(float(keep.sum()/len(base)),3),round(float(np.median(widths)),2)


def intersection(first,second):
    v,p=first[:2],first[2:];w,q=second[:2],second[2:]
    matrix=np.column_stack((v,-w))
    if abs(np.linalg.det(matrix))<.15: return None
    return p+float(np.linalg.solve(matrix,q-p)[0])*v


def verify_quad(image,quad,gray=None,paper=None):
    if gray is None:
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    fits=[fit_side(gray,quad[i],quad[(i+1)%4]) for i in range(4)]
    if any(side is None for side in fits): return None
    refined=[]
    for i in range(4):
        p=intersection(fits[i-1][0],fits[i][0])
        if p is None or not np.isfinite(p).all() or np.linalg.norm(p-quad[i])>16: return None
        refined.append(p)
    refined=np.float32(refined)
    if not cv2.isContourConvex(refined.reshape(-1,1,2)) or cv2.contourArea(refined,oriented=True)>=0: return None
    if abs(cv2.contourArea(refined))<5000: return None
    if (refined[:,0]<12).any() or (refined[:,0]>=image.shape[1]-12).any() or (refined[:,1]<12).any() or (refined[:,1]>=image.shape[0]-12).any(): return None
    if paper is None:
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        paper=(hsv[:,:,1]<120)&(hsv[:,:,2]>110)
    inside=np.zeros(gray.shape,np.uint8);cv2.fillConvexPoly(inside,np.int32(refined),255)
    inside=cv2.erode(inside,np.ones((9,9),np.uint8))>0
    if not inside.any() or float(paper[inside].mean())<.65: return None
    return dict(points=refined,side_support=[f[1] for f in fits],stroke_width_px=[f[2] for f in fits])


def matches_reference_shape(points, reference):
    """Validate board shape against the confirmed reference; allow bed translation.

    All corners are measured in the current image. Substantial camera pose or
    scale changes require a new reference instead of relabelling another rectangle.
    """
    if reference is None:
        return True
    transform=cv2.getPerspectiveTransform(np.float32(reference),BOARD)
    rectified=cv2.perspectiveTransform(np.float32(points).reshape(1,4,2),transform)[0]
    sides=np.roll(rectified,-1,axis=0)-rectified
    lengths=np.linalg.norm(sides,axis=1)
    if not np.isfinite(rectified).all() or (lengths<140).any() or (lengths>280).any():
        return False
    directions=sides/lengths[:,None]
    return bool(np.max(np.abs(np.sum(directions*np.roll(directions,-1,axis=0),axis=1)))<.3)


def line_candidates(image,gray=None,paper=None,reference=None):
    """Bridge short reflection gaps using independent thick line fragments."""
    if gray is None:
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    mask=cv2.morphologyEx(np.uint8(gray<160)*255,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
    segments=cv2.HoughLinesP(cv2.Canny(mask,40,110),1,np.pi/720,45,minLineLength=90,maxLineGap=25)
    if segments is None: return []
    segments=sorted(segments.reshape(-1,4),key=lambda p:float(np.linalg.norm(p[2:]-p[:2])),reverse=True)
    families=[[],[]]
    for segment in segments[:100]:
        a,b=np.float32(segment[:2]),np.float32(segment[2:]);delta=b-a
        if abs(delta[1])<abs(delta[0])*.35: family=0
        elif abs(delta[0])<abs(delta[1])*.7: family=1
        else: continue
        fit=fit_side(gray,a,b)
        if fit is None or fit[2]<2.25: continue
        line=fit[0]
        duplicate=False
        for other in families[family]:
            normal=np.array([-other[1],other[0]])
            if abs(np.dot(line[:2],other[:2]))>.995 and abs(np.dot(line[2:]-other[2:],normal))<6:
                duplicate=True;break
        if not duplicate and len(families[family])<7: families[family].append(line)
    proposals=[]
    for top,bottom in combinations(families[0],2):
        for left,right in combinations(families[1],2):
            points=[intersection(bottom,left),intersection(bottom,right),intersection(top,right),intersection(top,left)]
            if any(p is None for p in points): continue
            quad=order_corners(points)
            if quad is None or not cv2.isContourConvex(quad.reshape(-1,1,2)) or abs(cv2.contourArea(quad))<5000: continue
            if not matches_reference_shape(quad,reference): continue
            found=verify_quad(image,quad,gray,paper)
            if found is not None and min(found['side_support'])>=.80:
                if not any(np.max(np.linalg.norm(c['points']-found['points'],axis=1))<8 for c in proposals):
                    proposals.append(found)
    return proposals


def discard_thinner_interior_grid(candidates):
    retained=[]
    for inner in candidates:
        discard=False
        for outer in candidates:
            if abs(cv2.contourArea(outer['points']))<=1.15*abs(cv2.contourArea(inner['points'])): continue
            if any(cv2.pointPolygonTest(outer['points'],tuple(map(float,p)),True)<-8 for p in inner['points']): continue
            # Suppress an interior sub-rectangle only when its interior side is
            # distinctly thinner than the parallel outer marker stroke.
            for i in range(4):
                a,b=inner['points'][i],inner['points'][(i+1)%4];mid=(a+b)/2
                if abs(cv2.pointPolygonTest(outer['points'],tuple(map(float,mid)),True))<8: continue
                direction=(b-a)/np.linalg.norm(b-a)
                parallel=[]
                for j in range(4):
                    v=outer['points'][(j+1)%4]-outer['points'][j];v=v/np.linalg.norm(v)
                    if abs(np.dot(v,direction))>.9: parallel.append(outer['stroke_width_px'][j])
                if parallel and inner['stroke_width_px'][i]<.90*min(parallel): discard=True
            if discard: break
        if not discard: retained.append(inner)
    return retained


def find_border(image,reference=None):
    if not isinstance(image,np.ndarray) or image.ndim!=3 or image.shape[2]!=3:
        raise ValueError('Expected a decoded color camera image')
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    paper=(hsv[:,:,1]<120)&(hsv[:,:,2]>110)
    candidates=[]
    for threshold in (110,130,150,170):
        mask=np.uint8(gray<threshold)*255
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area=abs(cv2.contourArea(contour))
            if not 5000<=area<=image.shape[0]*image.shape[1]*.92: continue
            polygon=cv2.approxPolyDP(contour,.015*cv2.arcLength(contour,True),True)
            if len(polygon)!=4 or not cv2.isContourConvex(polygon): continue
            quad=order_corners(polygon)
            if quad is None: continue
            if not matches_reference_shape(quad,reference): continue
            found=verify_quad(image,quad,gray,paper)
            if found is None: continue
            # Thresholds, and inner/outer contours of the same stroke, are duplicates.
            if any(np.max(np.linalg.norm(c['points']-found['points'],axis=1))<8 for c in candidates): continue
            candidates.append(found)
    for found in line_candidates(image,gray,paper,reference):
        if not any(np.max(np.linalg.norm(c['points']-found['points'],axis=1))<8 for c in candidates):
            candidates.append(found)
    candidates=discard_thinner_interior_grid(candidates)
    if len(candidates)!=1:
        return None,dict(status='border_not_found' if not candidates else 'border_ambiguous',
                         mode='thick_border',candidate_count=len(candidates))
    found=candidates[0]
    return found['points'],dict(status='valid',mode='thick_border',candidate_count=1,
        side_support=found['side_support'],stroke_width_px=found['stroke_width_px'],
        board_polygon_px=found['points'].tolist(),orientation='reference_bottom_left_right_up')


class ThickBorder:
    def __init__(self,image,calibration):
        self.reference=np.asarray(calibration['pixel_points'],np.float32)

    def locate(self,image):
        points,info=find_border(image,self.reference)
        if points is None: return None,info
        # A symmetric border cannot infer labelled orientation after large rotations.
        # Keep the upright reference convention; require recalibration if tilted too far.
        for i in (0,1):
            ref=self.reference[(i+1)%4]-self.reference[i]
            now=points[(i+1)%4]-points[i]
            cosine=float(np.dot(ref,now)/(np.linalg.norm(ref)*np.linalg.norm(now)))
            if cosine<.82:
                return None,dict(status='border_orientation_changed',mode='thick_border')
        matrix=cv2.getPerspectiveTransform(points,BOARD)
        if not np.isfinite(matrix).all(): return None,dict(status='border_invalid',mode='thick_border')
        info['image_to_board_homography']=matrix.tolist()
        return matrix,info
