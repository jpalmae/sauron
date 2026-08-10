from __future__ import annotations

import numpy as np

from ..types import Detection
from .base import Detector
from .onnx_dnn import OnnxDnnDetector
from .pose import OnnxPoseDetector

# COCO "seats" (kept as a legacy fallback default for the objects model).
SEAT_CLASSES: dict[int, str] = {56: "chair", 57: "couch"}

# When the pose model hallucinates a "person" on a screen/monitor, the objects
# model still tags it as tv/laptop. If a person box coincides with one of these
# (high IoU) it is almost certainly the screen, not a person -> drop it.
_SCREEN_CLASSES = {"tv", "laptop"}
_SCREEN_IOU = 0.6


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter / (area_a + area_b - inter + 1e-6)


class MultiDetector(Detector):
    """Runs a pose model (person + keypoints) and an object model (chairs, etc).

    Merges both into a single detection list so the tracker and rules see
    people (with keypoints, for posture) and objects (chairs, laptops, ...).
    False "person" detections over a screen/monitor are suppressed using the
    object model's tv/laptop boxes.
    """

    def __init__(
        self,
        pose_path: str,
        objects_path: str,
        input_size: tuple[int, int] = (640, 640),
        conf_threshold: float = 0.5,
        nms_threshold: float = 0.45,
        pose_classes: dict[int, str] | None = None,
        objects_classes: dict[int, str] | None = None,
    ) -> None:
        self.pose = OnnxPoseDetector(
            pose_path, input_size, conf_threshold, nms_threshold, pose_classes
        )
        # The object model must NOT also detect "person" (class 0) — that's the
        # pose model's job and would create duplicate / false persons (no keypoints).
        obj_classes = {k: v for k, v in (objects_classes or SEAT_CLASSES).items() if k != 0}
        self.objects = OnnxDnnDetector(
            objects_path, input_size, conf_threshold, nms_threshold, obj_classes
        )

    def detect(self, image: np.ndarray) -> list[Detection]:
        people = self.pose.detect(image)
        objs = self.objects.detect(image)
        screens = [o for o in objs if o.class_name in _SCREEN_CLASSES]
        if screens:
            people = [
                p for p in people
                if not any(_iou(p.bbox, s.bbox) >= _SCREEN_IOU for s in screens)
            ]
        return people + objs
