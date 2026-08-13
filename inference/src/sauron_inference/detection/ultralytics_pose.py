from __future__ import annotations

import os

import numpy as np

from ..types import Detection
from .base import Detector

_TORSO_KP = (5, 6, 11, 12)


class UltralyticsPoseDetector(Detector):
    """YOLOv8-pose on GPU via ultralytics (PyTorch + CUDA).

    Drops in for OnnxPoseDetector but runs inference on the GPU (10-20x faster
    than CPU ONNX). Requires ultralytics + torch with CUDA in the container.
    """

    def __init__(
        self,
        model_path: str = "yolov8n-pose.pt",
        input_size: tuple[int, int] = (640, 640),
        conf_threshold: float = 0.4,
        nms_threshold: float = 0.45,
        classes: dict[int, str] | None = None,
    ) -> None:
        from ultralytics import YOLO

        self.model = YOLO(model_path)
        self.conf_threshold = conf_threshold
        self.classes = classes or {0: "person"}
        self.min_torso_conf = float(os.environ.get("SAURON_POSE_MIN_TORSO_CONF", "0.30"))
        self.min_torso_points = int(os.environ.get("SAURON_POSE_MIN_TORSO_POINTS", "2"))

    def _is_real_person(self, kp: np.ndarray | None) -> bool:
        if kp is None:
            return False
        try:
            return sum(1 for i in _TORSO_KP if float(kp[i][2]) >= self.min_torso_conf) >= self.min_torso_points
        except Exception:
            return False

    def detect(self, image: np.ndarray) -> list[Detection]:
        results = self.model(image, verbose=False, conf=self.conf_threshold, imgsz=640)
        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return []

        detections: list[Detection] = []
        for i in range(len(r.boxes)):
            x1, y1, x2, y2 = r.boxes.xyxy[i].cpu().numpy()
            score = float(r.boxes.conf[i].cpu())
            kp = None
            if r.keypoints is not None:
                xy = r.keypoints.xy[i].cpu().numpy()
                conf = r.keypoints.conf[i].cpu().numpy().reshape(-1, 1)
                kp = np.hstack([xy, conf]).astype(np.float32)
            if not self._is_real_person(kp):
                continue
            detections.append(
                Detection(
                    bbox=np.array([x1, y1, x2, y2], dtype=np.float32),
                    score=score,
                    class_id=0,
                    class_name=self.classes.get(0, "person"),
                    keypoints=kp,
                )
            )
        return detections
