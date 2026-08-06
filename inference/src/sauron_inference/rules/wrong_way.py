from __future__ import annotations

from collections import deque

import numpy as np

from ..config import PolygonConfig
from ..types import Frame, TrackedObject
from .base import Rule, RuleContext
from .events import Event, EventType, Priority
from .geometry import cosine_similarity, point_in_polygon

_MIN_DISPLACEMENT_PX = 2.0


class WrongWayRule(Rule):
    """Alerts when a track moves against the allowed lane direction.

    Condition: cos(trajectory, lane_direction) < threshold sustained for
    >= wrong_way_seconds while inside the polygon. High priority.
    """

    def __init__(self, cfg: PolygonConfig) -> None:
        if cfg.direction is None:
            raise ValueError(f"polygon {cfg.id}: wrong_way rule requires a direction")
        self.cfg = cfg
        self.rule_id = f"wrong-way:{cfg.id}"
        self._polygon = np.array(cfg.points, dtype=np.float32)
        self._direction = np.array(cfg.direction, dtype=np.float64)
        self._samples: dict[int, deque[tuple[float, float]]] = {}
        self._alerted: set[int] = set()
        self._last_seen: dict[int, float] = {}

    def process(
        self, frame: Frame, tracks: list[TrackedObject], ctx: RuleContext
    ) -> list[Event]:
        events: list[Event] = []
        now = frame.timestamp
        th = ctx.thresholds
        window = max(2, ctx.fps // 2)
        for track in tracks:
            oid = track.object_id
            self._last_seen[oid] = now
            if not point_in_polygon(track.centroid, self._polygon):
                self._samples.pop(oid, None)
                self._alerted.discard(oid)
                continue
            history = track.track_history[-window:]
            if len(history) < 2:
                continue
            displacement = np.array(history[-1]) - np.array(history[0])
            if np.linalg.norm(displacement) < _MIN_DISPLACEMENT_PX:
                continue  # stationary: not evidence either way
            cos = cosine_similarity(displacement, self._direction)
            samples = self._samples.setdefault(oid, deque(maxlen=ctx.fps * 10))
            samples.append((now, cos))
            if oid in self._alerted:
                continue
            recent = [(t, c) for t, c in samples if now - t <= th.wrong_way_seconds]
            if not recent:
                continue
            span = recent[-1][0] - recent[0][0]
            if span >= th.wrong_way_seconds and all(c < th.wrong_way_cosine for _, c in recent):
                self._alerted.add(oid)
                events.append(
                    Event(
                        event_type=EventType.WRONG_WAY,
                        camera_id=ctx.camera_id,
                        timestamp=now,
                        confidence=track.score,
                        priority=Priority.CRITICAL,
                        rule_id=self.rule_id,
                        object_id=oid,
                        metadata={
                            "polygon_id": self.cfg.id,
                            "vehicle_class": track.class_name,
                            "cosine": round(cos, 3),
                            "sustained_seconds": round(span, 1),
                            "centroid": list(track.centroid),
                            "speed_kmh": (
                                round(track.speed_kmh, 1) if track.speed_kmh else None
                            ),
                        },
                    )
                )
        self._purge(self._last_seen, now)
        return events

    def _drop_object(self, object_id: int) -> None:
        self._samples.pop(object_id, None)
        self._alerted.discard(object_id)
