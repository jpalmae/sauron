from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..types import Detection
from .base import Detector
from .yolo_postprocess import postprocess_yolo


class OnnxDnnDetector(Detector):
    """YOLOv8 ONNX on CPU via OpenCV DNN — zero extra deps, works on ARM64.

    Useful for demos, development and CPU-only edge boxes. Expect ~5-15 FPS
    per stream at 640px on a modern CPU core.
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
            raise FileNotFoundError(f"onnx model not found: {onnx_path}")
        self.net = cv2.dnn.readNetFromONNX(str(onnx_path))
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold
        self.classes = classes or {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

    def detect(self, image: np.ndarray) -> list[Detection]:
        from .yolo_postprocess import letterbox

        padded, scale, pad = letterbox(image, self.input_size)
        blob = cv2.dnn.blobFromImage(padded, 1 / 255.0, self.input_size, swapRB=True)
        self.net.setInput(blob)
        output = self.net.forward()  # [1, 4+nc, N]
        return postprocess_yolo(
            output,
            orig_shape=image.shape[:2],
            scale=scale,
            pad=pad,
            conf_threshold=self.conf_threshold,
            nms_threshold=self.nms_threshold,
            classes=self.classes,
        )
