from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(slots=True)
class Frame:
    camera_id: str
    seq: int
    image: np.ndarray
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class Detection:
    bbox: np.ndarray  # xyxy, float32, shape (4,)
    score: float
    class_id: int
    class_name: str
    keypoints: np.ndarray | None = None  # [17, 3] (x, y, conf) for pose backends


@dataclass(slots=True)
class TrackedObject:
    object_id: int
    camera_id: str
    class_name: str
    class_id: int
    bbox: tuple[float, float, float, float]  # xyxy
    score: float
    centroid: tuple[float, float]
    velocity: tuple[float, float]  # px/frame, from Kalman state
    track_history: list[tuple[float, float]]
    frame_seq: int
    timestamp: float
    speed_kmh: float | None = None
    keypoints: np.ndarray | None = None  # [17, 3] (x, y, conf) for pose backends

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "camera_id": self.camera_id,
            "class_name": self.class_name,
            "class_id": self.class_id,
            "bbox": list(self.bbox),
            "score": round(self.score, 4),
            "centroid": list(self.centroid),
            "velocity": list(self.velocity),
            "track_history": [list(p) for p in self.track_history],
            "frame_seq": self.frame_seq,
            "timestamp": self.timestamp,
            "speed_kmh": round(self.speed_kmh, 1) if self.speed_kmh is not None else None,
        }
