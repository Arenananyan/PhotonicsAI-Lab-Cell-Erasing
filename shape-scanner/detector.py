"""Detect closed dark outlines on light paper; no learned model or coordinates API."""
import cv2
import numpy as np

COLORS = {'triangle': (103, 218, 67), 'quadrilateral': (255, 181, 65)}


def detect_shapes(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    smooth = cv2.GaussianBlur(gray, (5, 5), 0)
    binary = cv2.adaptiveThreshold(smooth, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 101, 15)
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    if hierarchy is None:
        return image.copy(), []
    height, width = gray.shape
    for i, contour in enumerate(contours):
        area = cv2.contourArea(contour)
        if not 150 <= area <= width * height * .15:
            continue
        perimeter = cv2.arcLength(contour, True)
        poly = cv2.approxPolyDP(contour, .035 * perimeter, True)
        if len(poly) not in (3, 4) or not cv2.isContourConvex(poly):
            continue
        hull_area = cv2.contourArea(cv2.convexHull(contour))
        if area / max(hull_area, 1) < .80:
            continue
        # Closed pen outlines contain a large light interior. Ignore solid
        # objects, paper edges, and most incidental hardware contours.
        children = []
        child = int(hierarchy[0, i, 2])
        while child != -1:
            children.append(contours[child])
            child = int(hierarchy[0, child, 0])
        if not children:
            continue
        inner = max(children, key=cv2.contourArea)
        ratio = cv2.contourArea(inner) / area
        if not .18 < ratio < .93:
            continue
        inner_poly = cv2.approxPolyDP(inner, .04 * cv2.arcLength(inner, True), True)
        if len(inner_poly) != len(poly) or not cv2.isContourConvex(inner_poly):
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if min(w, h) < 18 or not .25 < w / h < 4:
            continue
        if x <= 2 or y <= 2 or x + w >= width - 2 or y + h >= height - 2:
            continue
        mask = np.zeros(gray.shape, np.uint8)
        cv2.drawContours(mask, [contour], -1, 255, -1)
        interior = np.zeros_like(mask)
        cv2.drawContours(interior, [inner], -1, 255, -1)
        stroke = cv2.subtract(mask, interior)
        outside = cv2.subtract(cv2.dilate(mask, np.ones((9, 9), np.uint8)), mask)
        paper_level = cv2.mean(gray, mask=outside)[0]
        ink_level = cv2.mean(gray, mask=stroke)[0]
        inside_level = cv2.mean(gray, mask=interior)[0]
        if paper_level < 100 or inside_level < 100 or min(paper_level, inside_level) - ink_level < 30:
            continue
        name = 'triangle' if len(poly) == 3 else 'quadrilateral'
        candidates.append((name, (x, y, w, h), poly, area))
    # Nested contours can represent the same outline; retain the largest.
    selected = []
    for candidate in sorted(candidates, key=lambda item: item[3], reverse=True):
        x, y, w, h = candidate[1]
        if any(abs(x-a[1][0]) < .3*w and abs(y-a[1][1]) < .3*h
               for a in selected):
            continue
        selected.append(candidate)
    selected.sort(key=lambda item: (item[1][0], item[1][1]))
    annotated = image.copy()
    detections = []
    for number, (name, (x, y, w, h), poly, _) in enumerate(selected, 1):
        color = COLORS[name]
        cv2.polylines(annotated, [poly], True, color, 2, cv2.LINE_AA)
        cv2.rectangle(annotated, (x-5, y-5), (x+w+5, y+h+5), color, 2)
        text = f'{number}. {name.capitalize()}'
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, .55, 1)
        ty = max(th+8, y-12)
        tx = max(0, min(x-5, width-tw-12))
        cv2.rectangle(annotated, (tx, ty-th-6), (tx+tw+10, ty+5), color, -1)
        cv2.putText(annotated, text, (tx+5, ty), cv2.FONT_HERSHEY_SIMPLEX,
                    .55, (12, 23, 30), 1, cv2.LINE_AA)
        detections.append({'number': number, 'shape': name})
    return annotated, detections
