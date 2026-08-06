from __future__ import annotations

import numpy as np

from ..types import Detection
from .base import Detector


class MockDetector(Detector):
    """Detects the bright rectangles drawn by SyntheticSource. For tests/benchmarks."""

    def __init__(
        self,
        classes: dict[int, str] | None = None,
        conf_threshold: float = 0.5,
    ) -> None:
        self.classes = classes or {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
        self.conf_threshold = conf_threshold

    def detect(self, image: np.ndarray) -> list[Detection]:
        gray = image.mean(axis=2)
        mask = (gray > 100).astype(np.uint8)
        n, _, stats, _ = __import__("cv2").connectedComponentsWithStats(mask, connectivity=8)
        dets: list[Detection] = []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if area < 500:
                continue
            dets.append(
                Detection(
                    bbox=np.array([x, y, x + w, y + h], dtype=np.float32),
                    score=0.9,
                    class_id=2,
                    class_name=self.classes.get(2, "car"),
                )
            )
        return dets
