from __future__ import annotations

import numpy as np

from ..types import TrackedObject

_VEHICLE_CLASSES = {"car", "bus", "truck", "motorcycle"}
_MIN_BBOX_H = 40  # px; below this plates are unreadable anyway


def alpr_crop(image: np.ndarray, track: TrackedObject) -> np.ndarray | None:
    """Crop the most plate-likely region of a vehicle track.

    Heuristic v1 (no plate detector model): full width of the bbox, lower 60%
    for cars/trucks, full bbox for motorcycles. Real deployments can swap this
    for a trained plate detector without touching the rest of the pipeline.
    """
    if track.class_name not in _VEHICLE_CLASSES:
        return None
    x1, y1, x2, y2 = track.bbox
    h = y2 - y1
    if h < _MIN_BBOX_H:
        return None
    img_h, img_w = image.shape[:2]
    if track.class_name == "motorcycle":
        cx = int((x1 + x2) / 2)
        half = int((x2 - x1) * 0.6)
        x1, x2 = cx - half, cx + half
    else:
        y1 = y1 + h * 0.4
    xa, ya = max(0, int(x1)), max(0, int(y1))
    xb, yb = min(img_w, int(x2)), min(img_h, int(y2))
    if xb - xa < 20 or yb - ya < 12:
        return None
    return image[ya:yb, xa:xb]
