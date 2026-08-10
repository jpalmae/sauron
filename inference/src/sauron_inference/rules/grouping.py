from __future__ import annotations

import numpy as np

from ..config import PolygonConfig
from ..types import Frame, TrackedObject
from .base import Rule, RuleContext
from .events import Event, EventType, Priority
from .geometry import point_in_polygon


class GroupingRule(Rule):
    """Gathering detection: clusters of people close together in the zone.

    Thresholds (min people, distance) are read from ctx.defaults so they are
    GUI-tunable via the engine config.
    """

    def __init__(self, cfg: PolygonConfig) -> None:
        self.cfg = cfg
        self.rule_id = f"grouping:{cfg.id}"
        self._polygon = np.array(cfg.points, dtype=np.float32)
        self._last_emit: float = float("-inf")

    @staticmethod
    def _clusters(centroids: list[tuple[float, float]], distance_px: float) -> list[list[int]]:
        n = len(centroids)
        if n == 0:
            return []
        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        d2 = distance_px ** 2
        for i in range(n):
            xi, yi = centroids[i]
            for j in range(i + 1, n):
                xj, yj = centroids[j]
                if (xi - xj) ** 2 + (yi - yj) ** 2 <= d2:
                    parent[find(i)] = find(j)
        groups: dict[int, list[int]] = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)
        return list(groups.values())

    def process(self, frame: Frame, tracks: list[TrackedObject], ctx: RuleContext) -> list[Event]:
        d = ctx.defaults
        min_people = getattr(d, "grouping_min_people", 3) if d else 3
        distance_px = getattr(d, "grouping_distance_px", 220.0) if d else 220.0

        now = frame.timestamp
        if now - self._last_emit < ctx.thresholds.occupancy_interval_s:
            return []
        self._last_emit = now

        inside = [t for t in tracks if t.class_name == "person" and point_in_polygon(t.centroid, self._polygon)]
        clusters = self._clusters([t.centroid for t in inside], distance_px)
        big = [len(c) for c in clusters if len(c) >= min_people]
        if not big:
            return []

        return [
            Event(
                event_type=EventType.GROUPING,
                camera_id=ctx.camera_id,
                timestamp=now,
                confidence=1.0,
                priority=Priority.INFO,
                rule_id=self.rule_id,
                metadata={
                    "polygon_id": self.cfg.id,
                    "groups": big,
                    "groups_count": len(big),
                    "largest": max(big),
                    "people_in_groups": sum(big),
                },
            )
        ]
