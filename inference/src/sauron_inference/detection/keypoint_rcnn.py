from __future__ import annotations

import os

import cv2
import numpy as np

from ..types import Detection
from .base import Detector

_TORSO_KP = (5, 6, 11, 12)


class KeypointRCNNDetector(Detector):
    """Person detection + COCO 17 keypoints via torchvision KeypointRCNN.

    Replaces YOLOv8-pose with a BSD-3 licensed model (torchvision) that outputs
    the same 17 COCO keypoints — so all rules (posture, falls, occupancy,
    grouping) work unchanged. Runs on GPU (PyTorch + CUDA).
    """

    def __init__(
        self,
        model_path: str = "",
        input_size: tuple[int, int] = (640, 640),
        conf_threshold: float = 0.4,
        nms_threshold: float = 0.45,
        classes: dict[int, str] | None = None,
    ) -> None:
        import torch
        from torchvision.models.detection import (
            KeypointRCNN_ResNet50_FPN_Weights,
            keypointrcnn_resnet50_fpn,
        )

        weights = KeypointRCNN_ResNet50_FPN_Weights.DEFAULT
        self.model = keypointrcnn_resnet50_fpn(weights=weights)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.model.eval()
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
        import torch
        from torchvision.transforms.functional import to_tensor

        # BGR (OpenCV) -> RGB -> CHW tensor [0,1]
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        tensor = to_tensor(rgb).to(self.device)

        with torch.no_grad():
            preds = self.model([tensor])[0]

        boxes = preds["boxes"].cpu().numpy()
        scores = preds["scores"].cpu().numpy()
        labels = preds["labels"].cpu().numpy()
        keypoints = preds["keypoints"].cpu().numpy()  # [N, 17, 3] (x, y, vis)

        detections: list[Detection] = []
        for i in range(len(boxes)):
            if labels[i] != 1 or scores[i] < self.conf_threshold:
                continue  # only persons (COCO label 1) above threshold
            x1, y1, x2, y2 = boxes[i]
            kp = keypoints[i] if len(keypoints) > i else None  # [17, 3]
            if not self._is_real_person(kp):
                continue  # torso gate (same as YOLO)
            detections.append(
                Detection(
                    bbox=np.array([x1, y1, x2, y2], dtype=np.float32),
                    score=float(scores[i]),
                    class_id=0,
                    class_name="person",
                    keypoints=kp.astype(np.float32) if kp is not None else None,
                )
            )
        return detections
