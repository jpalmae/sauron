from __future__ import annotations

import cv2
import numpy as np

from ..config import PrivacyConfig
from ..types import TrackedObject

_VEHICLE_CLASSES = {"car", "bus", "truck", "motorcycle"}


def _blur_region(img: np.ndarray, box: tuple[int, int, int, int], strength: int) -> None:
    x1, y1, x2, y2 = box
    h, w = img.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return
    k = strength if strength % 2 == 1 else strength + 1
    roi = img[y1:y2, x1:x2]
    img[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)


def redact_frame(
    image: np.ndarray, tracks: list[TrackedObject], cfg: PrivacyConfig
) -> np.ndarray:
    """Return a redacted copy: blurred faces (top third of person boxes) and
    plates (lower band of vehicle boxes)."""
    out = image.copy()
    for t in tracks:
        x1, y1, x2, y2 = [int(v) for v in t.bbox]
        h = y2 - y1
        if cfg.blur_faces and t.class_name == "person":
            _blur_region(out, (x1, y1, x2, y1 + h // 3), cfg.strength)
        if cfg.blur_plates and t.class_name in _VEHICLE_CLASSES:
            _blur_region(out, (x1, int(y1 + h * 0.55), x2, y2), cfg.strength)
    return out
