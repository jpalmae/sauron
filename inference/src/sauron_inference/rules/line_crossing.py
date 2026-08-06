from __future__ import annotations

import numpy as np

from ..config import LineConfig
from ..types import Frame, TrackedObject
from .base import Rule, RuleContext
from .events import Event, EventType, Priority
from .geometry import cross_sign, segment_crosses_line


class LineCrossingRule(Rule):
    """Counts objects whose centroid trajectory crosses a directed virtual line."""

    def __init__(self, cfg: LineConfig) -> None:
        self.cfg = cfg
        self.rule_id = cfg.id
        self.a: tuple[float, float] = cfg.points[0]
        self.b: tuple[float, float] = cfg.points[1]
        self._last_centroid: dict[int, tuple[float, float]] = {}
        self._last_seen: dict[int, float] = {}
        self._counted: set[int] = set()

    def process(
        self, frame: Frame, tracks: list[TrackedObject], ctx: RuleContext
    ) -> list[Event]:
        events: list[Event] = []
        now = frame.timestamp
        for track in tracks:
            oid = track.object_id
            if self.cfg.classes and track.class_name not in self.cfg.classes:
                continue
            curr = track.centroid
            if cross_sign(curr, self.a, self.b) == 0.0:
                continue  # exactly on the line: keep the last off-line position
            prev = self._last_centroid.get(oid)
            self._last_centroid[oid] = curr
            self._last_seen[oid] = now
            if prev is None or oid in self._counted:
                continue
            if not segment_crosses_line(prev, curr, self.a, self.b):
                continue
            self._counted.add(oid)
            events.append(self._make_event(track, prev, curr, ctx))
        self._purge(self._last_seen, now)
        for oid in [o for o in self._counted if o not in self._last_seen]:
            self._counted.discard(oid)
        return events

    def _make_event(
        self,
        track: TrackedObject,
        prev: tuple[float, float],
        curr: tuple[float, float],
        ctx: RuleContext,
    ) -> Event:
        side_from = cross_sign(prev, self.a, self.b)
        movement = np.array([curr[0] - prev[0], curr[1] - prev[1]])
        direction = "forward" if side_from < 0 else "reverse"
        if self.cfg.direction is not None:
            d = np.array(self.cfg.direction)
            direction = "forward" if float(movement @ d) > 0 else "reverse"
        return Event(
            event_type=EventType.LINE_CROSSING,
            camera_id=ctx.camera_id,
            timestamp=track.timestamp,
            confidence=track.score,
            priority=Priority.INFO,
            rule_id=self.rule_id,
            object_id=track.object_id,
            metadata={
                "line_id": self.cfg.id,
                "vehicle_class": track.class_name,
                "direction": direction,
                "centroid": list(curr),
                "speed_kmh": round(track.speed_kmh, 1) if track.speed_kmh else None,
            },
        )

    def _drop_object(self, object_id: int) -> None:
        self._last_centroid.pop(object_id, None)
