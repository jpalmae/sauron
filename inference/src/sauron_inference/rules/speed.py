from __future__ import annotations

import cv2
import numpy as np

from ..config import HomographyConfig


class SpeedEstimator:
    """Converts centroid motion to km/h using a pixel->meters homography."""

    def __init__(self, cfg: HomographyConfig) -> None:
        src = np.array(cfg.src_points, dtype=np.float32)
        dst = np.array(cfg.dst_points, dtype=np.float32)
        if len(src) == 4:
            self._H = cv2.getPerspectiveTransform(src, dst)
        else:
            H, _ = cv2.findHomography(src, dst)
            if H is None:
                raise ValueError("homography estimation failed")
            self._H = H
        self._last: dict[int, tuple[float, np.ndarray]] = {}

    def to_world(self, point: tuple[float, float]) -> np.ndarray:
        p = np.array([point[0], point[1], 1.0])
        w = self._H @ p
        return w[:2] / w[2]

    def update(
        self, object_id: int, centroid: tuple[float, float], timestamp: float
    ) -> float | None:
        """Returns speed in km/h, or None on the first sighting of a track."""
        world = self.to_world(centroid)
        prev = self._last.get(object_id)
        self._last[object_id] = (timestamp, world)
        if prev is None:
            return None
        dt = timestamp - prev[0]
        if dt <= 1e-3:
            return None
        dist_m = float(np.linalg.norm(world - prev[1]))
        return dist_m / dt * 3.6

    def purge(self, active_ids: set[int]) -> None:
        for oid in list(self._last):
            if oid not in active_ids:
                del self._last[oid]
