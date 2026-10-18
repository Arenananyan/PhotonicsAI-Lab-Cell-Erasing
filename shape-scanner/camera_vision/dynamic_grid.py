"""Reidentify a labelled reference grid and fit its image-to-board map each frame."""
import time
import cv2
import numpy as np


class DynamicGrid:
    def __init__(self, image: np.ndarray, calibration: dict):
        self.last = None
        self.reference_matrix = np.asarray(calibration['homography'], np.float64)
        self.sift = cv2.SIFT_create(nfeatures=2500, contrastThreshold=.025)
        mask = np.zeros(image.shape[:2], np.uint8)
        cv2.fillPoly(mask, [np.int32(calibration['pixel_points'])], 255)
        mask = cv2.dilate(mask, np.ones((71,71),np.uint8))
        self.keypoints, self.descriptors = self.features(image, mask)

    def features(self, image, board_mask=None):
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
        mask=np.uint8(hsv[:,:,1]<65)*255
        if board_mask is not None:
            mask=cv2.bitwise_and(mask,board_mask)
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        return self.sift.detectAndCompute(gray,mask)

    def _identify(self, image) -> tuple[np.ndarray | None, dict]:
        info={'status':'grid_reference_not_identified','mode':'dynamic_reference_grid'}
        keypoints, descriptors=self.features(image)
        if self.descriptors is None or descriptors is None or len(descriptors)<2:
            return None,info
        pairs=cv2.BFMatcher().knnMatch(self.descriptors,descriptors,k=2)
        matches=[pair[0] for pair in pairs if len(pair)==2 and pair[0].distance<.72*pair[1].distance]
        if len(matches)<10:
            return None,info
        ref=np.float32([self.keypoints[m.queryIdx].pt for m in matches])
        current=np.float32([keypoints[m.trainIdx].pt for m in matches])
        movement,inlier_mask=cv2.findHomography(ref,current,cv2.RANSAC,3)
        if movement is None or inlier_mask is None:
            return None,info
        selected=inlier_mask[:,0].astype(bool)
        inlier_count=int(selected.sum())
        info['matched_reference_points']=inlier_count
        if inlier_count<10 or inlier_count/len(matches)<.40:
            return None,info
        board=cv2.perspectiveTransform(ref.reshape(-1,1,2),self.reference_matrix).reshape(-1,2)
        known=board[selected]
        anchors=(known[:,0]<8)|(known[:,0]>192)|(known[:,1]<8)|(known[:,1]>192)
        anchor_count=int(anchors.sum())
        info['matched_axis_border_points']=anchor_count
        # An unlabelled interior lattice cannot establish an absolute origin.
        if anchor_count<6 or np.ptp(known[:,0])<90 or np.ptp(known[:,1])<90:
            return None,info
        try:
            matrix=self.reference_matrix@np.linalg.inv(movement)
            matrix/=matrix[2,2]
            inverse=np.linalg.inv(matrix)
        except np.linalg.LinAlgError:
            return None,info
        corners=cv2.perspectiveTransform(np.float32([[[0,0]],[[200,0]],[[200,200]],[[0,200]]]),inverse)
        if not np.isfinite(corners).all() or not cv2.isContourConvex(corners):
            return None,info
        if cv2.contourArea(corners,oriented=True)>=0 or abs(cv2.contourArea(corners))<2500:
            return None,info
        return self._verify(matrix, image, info)

    def _verify(self, matrix, image, info):
        try:
            inverse = np.linalg.inv(matrix)
        except np.linalg.LinAlgError:
            return None, info
        corners = cv2.perspectiveTransform(np.float32([[[0,0]],[[200,0]],[[200,200]],[[0,200]]]), inverse)
        if not np.isfinite(corners).all() or not cv2.isContourConvex(corners) or cv2.contourArea(corners, oriented=True)>=0 or abs(cv2.contourArea(corners))<2500:
            return None, info
        # Verify both families of known 50-mm lines in THIS frame.
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        edges=cv2.Canny(gray,25,75)
        distances=cv2.distanceTransform(255-edges,cv2.DIST_L2,3)
        family_support=[]
        intersections=[]
        board_intersections=[]
        for family in range(2):
            supports=[]
            for coordinate in (0,50,100,150,200):
                samples=np.float32([[coordinate,t] if family==0 else [t,coordinate]
                    for t in np.linspace(8,192,70)])
                pixels=cv2.perspectiveTransform(samples.reshape(-1,1,2),inverse).reshape(-1,2)
                scores=[]
                for x,y in pixels:
                    x,y=round(float(x)),round(float(y))
                    if 0<=x<image.shape[1] and 0<=y<image.shape[0]:
                        scores.append(distances[y,x]<=3)
                if len(scores)>=35:
                    supports.append(float(np.mean(scores)))
            family_support.append(supports)
        info['grid_line_support']=[round(float(np.mean(s)),3) if s else 0 for s in family_support]
        if any(len(s)<3 or sum(v>=.55 for v in s)<3 or np.mean(s)<.60 for s in family_support):
            info['status']='grid_lines_not_verified'
            return None,info
        # Refine the new transform at visible large-grid intersections.
        for x in (0,50,100,150,200):
            for y in (0,50,100,150,200):
                p=cv2.perspectiveTransform(np.float32([[[x,y]]]),inverse)[0,0]
                if 8<p[0]<image.shape[1]-8 and 8<p[1]<image.shape[0]-8:
                    refined=cv2.cornerSubPix(gray,p.reshape(1,1,2).copy(),(4,4),(-1,-1),
                        (cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_MAX_ITER,25,.02))[0,0]
                    if np.linalg.norm(refined-p)<=3:
                        intersections.append(refined)
                        board_intersections.append([x,y])
        if len(intersections)>=8:
            refined,mask=cv2.findHomography(np.float32(intersections),np.float32(board_intersections),cv2.RANSAC,1)
            if refined is not None and int(mask.sum())>=8:
                matrix=refined
                inverse=np.linalg.inv(matrix)
                corners=cv2.perspectiveTransform(np.float32([[[0,0]],[[200,0]],[[200,200]],[[0,200]]]),inverse)
                info['refined_grid_intersections']=int(mask.sum())
        info.update(status='valid',image_to_board_homography=matrix.tolist(),board_polygon_px=corners.reshape(-1,2).tolist())
        return matrix,info

    def locate(self, image):
        matrix, info = self._identify(image)
        if matrix is None:
            tracked, tracked_info = self._track(image)
            if tracked is not None:
                matrix, info = tracked, tracked_info
        if matrix is not None:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            mask = np.zeros(gray.shape, np.uint8)
            cv2.fillPoly(mask, [np.int32(info['board_polygon_px'])], 255)
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            mask[hsv[:,:,1]>=65]=0
            points = cv2.goodFeaturesToTrack(gray, 250, .01, 5, mask=mask)
            self.last = (gray, points, matrix, time.monotonic())
        return matrix, info

    def _track(self, image):
        info = {'status':'grid_reference_not_identified', 'mode':'dynamic_tracked_grid'}
        if self.last is None:
            return None, info
        previous, points, previous_matrix, timestamp = self.last
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if gray.shape!=previous.shape or points is None or len(points)<20 or time.monotonic()-timestamp>1:
            return None, info
        current, status, _ = cv2.calcOpticalFlowPyrLK(previous, gray, points, None)
        if current is None:
            return None, info
        back, back_status, _ = cv2.calcOpticalFlowPyrLK(gray, previous, current, None)
        if back is None:
            return None, info
        valid = status[:,0].astype(bool) & back_status[:,0].astype(bool) & (np.linalg.norm(points-back,axis=2)[:,0]<.8)
        old,new = points[valid],current[valid]
        if len(old)<20:
            return None, info
        movement, inliers = cv2.findHomography(old,new,cv2.RANSAC,2)
        if movement is None or inliers is None or int(inliers.sum())<20:
            return None, info
        known=cv2.perspectiveTransform(old[inliers[:,0].astype(bool)],previous_matrix).reshape(-1,2)
        anchors=(known[:,0]<8)|(known[:,0]>192)|(known[:,1]<8)|(known[:,1]>192)
        if int(anchors.sum())<6 or np.ptp(known[:,0])<90 or np.ptp(known[:,1])<90:
            return None, info
        try:
            matrix=previous_matrix@np.linalg.inv(movement)
            matrix/=matrix[2,2]
        except np.linalg.LinAlgError:
            return None, info
        info['tracked_points']=int(inliers.sum())
        return self._verify(matrix,image,info)


def draw_board(image, calibration: dict):
    """Show the currently located board, not the old reference pixel rectangle."""
    if calibration.get('status')!='valid' or 'board_polygon_px' not in calibration:
        return image
    result=image.copy()
    points=np.int32(np.round(calibration['board_polygon_px']))
    cv2.polylines(result,[points],True,(220,210,70),1,cv2.LINE_AA)
    origin = calibration.get('printer_origin_mm', {'x': 0.0, 'y': 0.0})
    corners = ((0, 0), (200, 0), (200, 200), (0, 200))
    labels = [f"{x + origin['x']:g},{y + origin['y']:g}" for x, y in corners]
    for point,text in zip(points, labels):
        x,y=map(int,point)
        if 0<=x<image.shape[1] and 0<=y<image.shape[0]:
            cv2.circle(result,(x,y),4,(220,210,70),-1)
            cv2.putText(result,text,(min(x+6,image.shape[1]-80),max(y-8,15)),
                        cv2.FONT_HERSHEY_SIMPLEX,.45,(220,210,70),1,cv2.LINE_AA)
    return result
