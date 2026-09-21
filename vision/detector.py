"""Classical quadrilateral detection. This does not recognize card ranks."""

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

Frame = NDArray[np.uint8]


@dataclass(frozen=True)
class Detection:
    corners: NDArray[np.float32]
    box: tuple[int, int, int, int]
    warped: Frame


def detect_cards(frame: Frame) -> list[Detection]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    threshold = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5)
    contours, _ = cv2.findContours(threshold, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    area = frame.shape[0] * frame.shape[1]
    detections: list[Detection] = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        size = cv2.contourArea(contour)
        if not area * 0.012 <= size <= area * 0.80:
            continue
        polygon = cv2.approxPolyDP(contour, 0.025 * cv2.arcLength(contour, True), True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        (_, _), (width, height), _ = cv2.minAreaRect(polygon)
        if min(width, height) <= 0 or not 1.2 <= max(width, height) / min(width, height) <= 1.9:
            continue
        x, y, w, h = cv2.boundingRect(polygon)
        duplicate = False
        for previous in detections:
            px, py, pw, ph = previous.box
            intersection = max(0, min(x + w, px + pw) - max(x, px)) * max(0, min(y + h, py + ph) - max(y, py))
            if intersection / min(w * h, pw * ph) > 0.8:
                duplicate = True
                break
        if duplicate:
            continue
        points = polygon.reshape(4, 2).astype(np.float32)
        center = points.mean(axis=0)
        points = points[np.argsort(np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0]))]
        points = np.roll(points, -int(np.argmin(points.sum(axis=1))), axis=0)
        if np.linalg.norm(points[1] - points[0]) > np.linalg.norm(points[2] - points[1]):
            points = np.roll(points, -1, axis=0)
        destination = np.array([[0, 0], [199, 0], [199, 299], [0, 299]], dtype=np.float32)
        transform = cv2.getPerspectiveTransform(points, destination)
        warped = cv2.warpPerspective(frame, transform, (200, 300))
        detections.append(Detection(points, (x, y, w, h), warped))
    return detections


def draw_detections(frame: Frame) -> Frame:
    preview = frame.copy()
    for detection in detect_cards(frame):
        cv2.polylines(preview, [detection.corners.astype(np.int32)], True, (169, 222, 163), 2)
        x, y, _, _ = detection.box
        cv2.putText(preview, "Card shape", (x, max(y - 8, 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (169, 222, 163), 1)
    return preview
