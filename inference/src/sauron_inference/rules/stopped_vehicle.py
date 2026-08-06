from __future__ import annotations

import math

import numpy as np

from ..config import PolygonConfig
from ..types import Frame, TrackedObject
from .base import Rule, RuleContext
from .events import Event, EventType, Priority
from .geometry import point_in_polygon


class StoppedVehicleRule(Rule):
    """Alerts when a track stays ~stationary inside a non-parking polygon."""

    def __init__(self, cfg: PolygonConfig) -> None:
        self.cfg = cfg
        self.rule_id = f"stopped:{cfg.id}"
        self._polygon = np.array(cfg.points, dtype=np.float32)
        self._stop_since: dict[int, float] = {}
        self._alerted: set[int] = set()
        self._last_seen: dict[int, float] = {}

    def process(
        self, frame: Frame, tracks: list[TrackedObject], ctx: RuleContext
    ) -> list[Event]:
        events: list[Event] = []
        now = frame.timestamp
        th = ctx.thresholds
        is_parking = self.cfg.kind == "parking"
        for track in tracks:
            oid = track.object_id
            self._last_seen[oid] = now
            speed_px_s = math.hypot(*track.velocity) * ctx.fps
            inside = point_in_polygon(track.centroid, self._polygon)
            if inside and speed_px_s < th.stopped_speed_epsilon:
                self._stop_since.setdefault(oid, now)
                stopped_for = now - self._stop_since[oid]
                if stopped_for >= th.stopped_seconds and oid not in self._alerted:
                    self._alerted.add(oid)
                    events.append(
                        Event(
                            event_type=(
                                EventType.STOPPED_VEHICLE
                                if not is_parking
                                else EventType.OBSTRUCTION
                            ),
                            camera_id=ctx.camera_id,
                            timestamp=now,
                            confidence=track.score,
                            priority=Priority.WARNING,
                            rule_id=self.rule_id,
                            object_id=oid,
                            metadata={
                                "polygon_id": self.cfg.id,
                                "vehicle_class": track.class_name,
                                "stopped_seconds": round(stopped_for, 1),
                                "centroid": list(track.centroid),
                                "bbox": list(track.bbox),
                            },
                        )
                    )
            else:
                self._stop_since.pop(oid, None)
                self._alerted.discard(oid)
        self._purge(self._last_seen, now)
        return events

    def _drop_object(self, object_id: int) -> None:
        self._stop_since.pop(object_id, None)
        self._alerted.discard(object_id)
