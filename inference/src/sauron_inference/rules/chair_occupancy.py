from __future__ import annotations

import numpy as np

from ..config import PolygonConfig
from ..types import Frame, TrackedObject
from .base import Rule, RuleContext
from .events import Event, EventType, Priority
from .geometry import point_in_polygon


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """IoU between two xyxy boxes."""
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-6)


class ChairOccupancyRule(Rule):
    """Seat utilization: counts chairs/couches and how many are occupied.

    A seat is "occupied" when a person's box overlaps it (IoU >= threshold).
    Emits a CHAIR_OCCUPANCY event with the breakdown.
    """

    SEAT_CLASSES = {"chair", "couch"}
    IOU_THRESHOLD = 0.15

    def __init__(self, cfg: PolygonConfig) -> None:
        self.cfg = cfg
        self.rule_id = f"chair_occupancy:{cfg.id}"
        self._polygon = np.array(cfg.points, dtype=np.float32)
        self._last_emit: float = float("-inf")

    def process(
        self, frame: Frame, tracks: list[TrackedObject], ctx: RuleContext
    ) -> list[Event]:
        now = frame.timestamp
        if now - self._last_emit < ctx.thresholds.occupancy_interval_s:
            return []
        self._last_emit = now

        seats = [t for t in tracks if t.class_name in self.SEAT_CLASSES]
        people = [
            t for t in tracks
            if t.class_name == "person" and point_in_polygon(t.centroid, self._polygon)
        ]

        occupied = 0
        for seat in seats:
            if any(_overlap(seat.bbox, p.bbox) >= self.IOU_THRESHOLD for p in people):
                occupied += 1
        total = len(seats)

        return [
            Event(
                event_type=EventType.CHAIR_OCCUPANCY,
                camera_id=ctx.camera_id,
                timestamp=now,
                confidence=1.0,
                priority=Priority.INFO,
                rule_id=self.rule_id,
                metadata={
                    "polygon_id": self.cfg.id,
                    "seats": total,
                    "occupied": occupied,
                    "free": max(0, total - occupied),
                    "utilization": round(occupied / total, 2) if total else None,
                },
            )
        ]
