from __future__ import annotations

import cv2
import numpy as np


def point_in_polygon(point: tuple[float, float], polygon: np.ndarray) -> bool:
    return cv2.pointPolygonTest(polygon.astype(np.float32), point, False) >= 0


def cross_sign(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Sign of the cross product (b-a) x (p-a): which side of line a->b p lies on."""
    return float((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]))


def segment_crosses_line(
    p1: tuple[float, float],
    p2: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> bool:
    """True if the segment p1->p2 changes side relative to the infinite line a->b."""
    s1 = cross_sign(p1, a, b)
    s2 = cross_sign(p2, a, b)
    if s1 == 0.0 or s2 == 0.0:
        return False
    return (s1 < 0) != (s2 < 0)


def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0
    return float(np.dot(v1, v2) / (n1 * n2))


def polygon_area(polygon: np.ndarray) -> float:
    return float(cv2.contourArea(polygon.astype(np.float32)))


def bbox_area(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
