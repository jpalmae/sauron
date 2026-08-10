from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np

from ..types import Detection
from .base import Detector
from .yolo_postprocess import letterbox, postprocess_yolo_pose

# Torso keypoints (COCO): left/right shoulder (5,6) + left/right hip (11,12).
# A real person shows a valid torso; jackets/backpacks/blobs don't, so this
# gate drops false "person" detections that would clutter analytics + overlay.
_TORSO_KP = (5, 6, 11, 12)


class OnnxPoseDetector(Detector):
    """YOLOv8-pose ONNX on CPU via OpenCV DNN.

    Returns person detections carrying 17 COCO keypoints, so downstream rules
    can classify posture (sitting/standing) and track per-person transitions.
    Detections without a credible torso are dropped (jackets, backpacks, blobs).
    """

    def __init__(
        self,
        onnx_path: str | Path,
        input_size: tuple[int, int] = (640, 640),
        conf_threshold: float = 0.5,
        nms_threshold: float = 0.45,
        classes: dict[int, str] | None = None,
    ) -> None:
        onnx_path = Path(onnx_path)
        if not onnx_path.exists():
            raise FileNotFoundError(f"pose model not found: {onnx_path}")
        self.net = cv2.dnn.readNetFromONNX(str(onnx_path))
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold
        self.classes = classes or {0: "person"}
        # Pose-quality gate (tunable without code changes)
        self.min_torso_conf = float(os.environ.get("SAURON_POSE_MIN_TORSO_CONF", "0.30"))
        self.min_torso_points = int(os.environ.get("SAURON_POSE_MIN_TORSO_POINTS", "2"))

    def _is_real_person(self, kp: np.ndarray | None) -> bool:
        if kp is None:
            return False
        try:
            ok = sum(1 for i in _TORSO_KP if float(kp[i][2]) >= self.min_torso_conf)
            return ok >= self.min_torso_points
        except Exception:
            return False

    def detect(self, image: np.ndarray) -> list[Detection]:
        padded, scale, pad = letterbox(image, self.input_size)
        blob = cv2.dnn.blobFromImage(padded, 1 / 255.0, self.input_size, swapRB=True)
        self.net.setInput(blob)
        output = self.net.forward()  # [1, 56, N]
        results = postprocess_yolo_pose(
            output,
            orig_shape=image.shape[:2],
            scale=scale,
            pad=pad,
            conf_threshold=self.conf_threshold,
            nms_threshold=self.nms_threshold,
        )
        detections: list[Detection] = []
        for box, score, kp in results:
            if not self._is_real_person(kp):
                continue  # drop jackets / backpacks / blobs without a real torso
            detections.append(
                Detection(
                    bbox=box,
                    score=score,
                    class_id=0,
                    class_name=self.classes.get(0, "person"),
                    keypoints=kp,
                )
            )
        return detections
