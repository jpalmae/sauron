from __future__ import annotations

import cv2
import numpy as np

_BINS = (8, 8)


def hsv_signature(image: np.ndarray, bbox: tuple[float, float, float, float]) -> list[float] | None:
    """Compact appearance signature: normalized HSV histogram (8x8 = 64 dims).

    Enough for cross-camera re-identification of vehicles over short windows.
    """
    x1, y1, x2, y2 = [int(v) for v in bbox]
    h, w = image.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 12 or y2 - y1 < 12:
        return None
    crop = image[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, list(_BINS), [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return [round(float(v), 4) for v in hist.flatten()]


def cosine_sim(a: list[float], b: list[float]) -> float:
    va = np.asarray(a, dtype=np.float64)
    vb = np.asarray(b, dtype=np.float64)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom < 1e-9:
        return 0.0
    return float(np.dot(va, vb) / denom)
