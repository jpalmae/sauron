from __future__ import annotations

import numpy as np

from ..config import PolygonConfig
from ..types import Frame, TrackedObject
from .base import Rule, RuleContext
from .events import Event, EventType, Priority
from .geometry import bbox_area, point_in_polygon, polygon_area


class CongestionRule(Rule):
    """Alerts when bbox occupancy of a polygon exceeds a threshold over time."""

    def __init__(self, cfg: PolygonConfig) -> None:
        self.cfg = cfg
        self.rule_id = f"congestion:{cfg.id}"
        self._polygon = np.array(cfg.points, dtype=np.float32)
        self._area = polygon_area(self._polygon)
        self._above_since: float | None = None
        self._last_alert: float = float("-inf")

    def occupancy(self, tracks: list[TrackedObject]) -> float:
        if self._area <= 0:
            return 0.0
        covered = sum(
            bbox_area(t.bbox) for t in tracks if point_in_polygon(t.centroid, self._polygon)
        )
        return min(1.0, covered / self._area)

    def process(
        self, frame: Frame, tracks: list[TrackedObject], ctx: RuleContext
    ) -> list[Event]:
        now = frame.timestamp
        th = ctx.thresholds
        occ = self.occupancy(tracks)
        if occ < th.congestion_occupancy:
            self._above_since = None
            return []
        self._above_since = self._above_since if self._above_since is not None else now
        sustained = now - self._above_since
        if sustained < th.congestion_seconds:
            return []
        if now - self._last_alert < th.congestion_cooldown_s:
            return []
        self._last_alert = now
        self._above_since = None
        return [
            Event(
                event_type=EventType.CONGESTION,
                camera_id=ctx.camera_id,
                timestamp=now,
                confidence=occ,
                priority=Priority.WARNING,
                rule_id=self.rule_id,
                metadata={
                    "polygon_id": self.cfg.id,
                    "occupancy": round(occ, 3),
                    "sustained_seconds": round(sustained, 1),
                    "vehicles_in_roi": sum(
                        1 for t in tracks if point_in_polygon(t.centroid, self._polygon)
                    ),
                },
            )
        ]
