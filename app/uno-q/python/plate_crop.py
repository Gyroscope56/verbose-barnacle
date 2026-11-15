"""Geometric correction and quality estimates for detected plate regions."""

import cv2
import numpy as np


def straighten_plate(frame, box):
    """Rectify a credible four-sided border near the detector box."""
    x, y, width, height = box
    pad_x, pad_y = max(2, round(width * 0.12)), max(2, round(height * 0.12))
    left, top = max(0, x - pad_x), max(0, y - pad_y)
    window = frame[top:y + height + pad_y, left:x + width + pad_x]
    gray = cv2.cvtColor(window, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, 35, 110)
    _, bright = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    kernel = np.ones((5, 5), np.uint8)
    contours = []
    for mask in (edges, bright):
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        found, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        contours.extend(found)
    center = np.array([x - left + width / 2, y - top + height / 2])
    box_area = width * height
    detector_quad = np.float32(
        [[x - left, y - top], [x - left + width, y - top],
         [x - left + width, y - top + height], [x - left, y - top + height]]
    )

    best_overlap = 0.0
    best_corners = None
    for contour in contours:
        area = cv2.contourArea(contour)
        if not 0.48 * box_area <= area <= 1.40 * box_area:
            continue
        quad = cv2.approxPolyDP(contour, 0.024 * cv2.arcLength(contour, True), True)
        if len(quad) != 4 or not cv2.isContourConvex(quad):
            continue
        corners = quad.reshape(4, 2).astype(np.float32)
        cx, cy = corners.mean(axis=0)
        if abs(cx - center[0]) > 0.20 * width or abs(cy - center[1]) > 0.20 * height:
            continue
        # OpenCV yields consecutive vertices. Put the top-left first, then go clockwise.
        corners = np.roll(corners, -int(np.argmin(corners.sum(axis=1))), axis=0)
        if corners[1, 0] < corners[-1, 0]:
            corners = corners[[0, 3, 2, 1]]
        sides = np.linalg.norm(corners - np.roll(corners, -1, axis=0), axis=1)
        if min(sides) < 7:
            continue
        ratio = (sides[0] + sides[2]) / (sides[1] + sides[3])
        if not 1.15 <= ratio <= 3.4:
            continue
        overlap = cv2.intersectConvexConvex(corners, detector_quad)[0]
        iou = overlap / (box_area + cv2.contourArea(corners) - overlap)
        if iou > best_overlap:
            best_overlap, best_corners = iou, corners

    if best_corners is None or best_overlap < 0.55:
        return None

    # Inset slightly to remove the frame surrounding the plate without trimming its text.
    inset = best_corners.mean(axis=0) + 0.95 * (best_corners - best_corners.mean(axis=0))
    out_width = max(14, round(max(np.linalg.norm(inset[1] - inset[0]),
                                  np.linalg.norm(inset[2] - inset[3]))))
    out_height = out_width // 2
    target = np.float32([[0, 0], [out_width - 1, 0], [out_width - 1, out_height - 1],
                         [0, out_height - 1]])
    return cv2.warpPerspective(
        window, cv2.getPerspectiveTransform(inset, target), (out_width, out_height)
    )


def crop_quality(crop):
    """Favor character detail and penalize highlight clipping on the crop."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, (160, 80), interpolation=cv2.INTER_AREA)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    clipped = float(np.mean(gray >= 250))
    return sharpness, clipped
