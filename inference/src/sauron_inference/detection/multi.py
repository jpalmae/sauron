from __future__ import annotations

import numpy as np

from ..types import Detection
from .base import Detector
from .onnx_dnn import OnnxDnnDetector
from .pose import OnnxPoseDetector

# COCO "seats" for chair-occupancy analytics
SEAT_CLASSES: dict[int, str] = {62: "chair", 63: "couch"}


class MultiDetector(Detector):
    """Runs a pose model (person + keypoints) and an object model (chairs, etc).

    Merges both into a single detection list so the tracker and rules see
    people (with keypoints, for posture) and seats (for chair occupancy).
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
        self.objects = OnnxDnnDetector(
            objects_path, input_size, conf_threshold, nms_threshold, objects_classes or SEAT_CLASSES
        )

    def detect(self, image: np.ndarray) -> list[Detection]:
        return self.pose.detect(image) + self.objects.detect(image)
