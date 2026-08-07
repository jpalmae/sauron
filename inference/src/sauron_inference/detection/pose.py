from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..types import Detection
from .base import Detector
from .yolo_postprocess import letterbox, postprocess_yolo_pose


class OnnxPoseDetector(Detector):
    """YOLOv8-pose ONNX on CPU via OpenCV DNN.

    Returns person detections carrying 17 COCO keypoints, so downstream rules
    can classify posture (sitting/standing) and track per-person transitions.
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
