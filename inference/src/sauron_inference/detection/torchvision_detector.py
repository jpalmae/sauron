from __future__ import annotations

import cv2
import numpy as np

from ..types import Detection
from .base import Detector

# COCO category IDs (1-indexed, as used by torchvision models)
_COCO_NAMES = {
    1: "person", 2: "bicycle", 3: "car", 4: "motorcycle", 6: "bus",
    7: "train", 8: "truck", 9: "boat", 13: "bench", 15: "bench",
}


class TorchvisionDetector(Detector):
    """COCO object detection via torchvision (BSD-3 license, no YOLO).

    Uses Faster R-CNN or RetinaNet pre-trained on COCO. Detects vehicles,
    persons and 78+ other classes. The ``classes`` dict VALUES (names) control
    which COCO classes to emit — e.g. ``{3: "car", 4: "motorcycle"}`` emits
    only cars and motorcycles, regardless of the key numbering.
    """

    def __init__(
        self,
        model_path: str = "",
        input_size: tuple[int, int] = (640, 640),
        conf_threshold: float = 0.5,
        nms_threshold: float = 0.45,
        classes: dict[int, str] | None = None,
    ) -> None:
        import torch
        from torchvision.models.detection import (
            FasterRCNN_ResNet50_FPN_Weights,
            RetinaNet_ResNet50_FPN_Weights,
            fasterrcnn_resnet50_fpn,
            retinanet_resnet50_fpn,
        )

        model_name = (model_path or "fasterrcnn").lower()
        if "retinanet" in model_name:
            self.model = retinanet_resnet50_fpn(weights=RetinaNet_ResNet50_FPN_Weights.DEFAULT)
        else:
            self.model = fasterrcnn_resnet50_fpn(weights=FasterRCNN_ResNet50_FPN_Weights.DEFAULT)

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.model.eval()
        self.conf_threshold = conf_threshold

        # Build the set of allowed class NAMES from the config classes dict
        desired = set((classes or {}).values())
        # Map COCO label ID -> class name, but only for desired names
        self._emit: dict[int, str] = {}
        for coco_id, name in _COCO_NAMES.items():
            if not desired or name in desired:
                self._emit[coco_id] = name

    def detect(self, image: np.ndarray) -> list[Detection]:
        import torch
        from torchvision.transforms.functional import to_tensor

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        tensor = to_tensor(rgb).to(self.device)

        with torch.no_grad():
            preds = self.model([tensor])[0]

        boxes = preds["boxes"].cpu().numpy()
        scores = preds["scores"].cpu().numpy()
        labels = preds["labels"].cpu().numpy()

        detections: list[Detection] = []
        for i in range(len(boxes)):
            cls = int(labels[i])
            if cls not in self._emit or scores[i] < self.conf_threshold:
                continue
            x1, y1, x2, y2 = boxes[i]
            detections.append(
                Detection(
                    bbox=np.array([x1, y1, x2, y2], dtype=np.float32),
                    score=float(scores[i]),
                    class_id=cls,
                    class_name=self._emit[cls],
                )
            )
        return detections
