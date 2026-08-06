from __future__ import annotations

import logging
from collections.abc import Callable

from ..config import PolygonConfig, PolygonRuleName, ROIConfig
from ..types import Frame, TrackedObject
from .base import Rule, RuleContext
from .congestion import CongestionRule
from .events import Event
from .line_crossing import LineCrossingRule
from .speed import SpeedEstimator
from .stopped_vehicle import StoppedVehicleRule
from .wrong_way import WrongWayRule

log = logging.getLogger(__name__)

_POLYGON_RULES: dict[PolygonRuleName, Callable[[PolygonConfig], Rule]] = {
    "stopped": StoppedVehicleRule,
    "wrong_way": WrongWayRule,
    "congestion": CongestionRule,
}


class RulesEngine:
    """Per-camera dispatcher: evaluates configured rules over tracked objects."""

    def __init__(self, camera_id: str, roi: ROIConfig, fps: int = 15) -> None:
        self.camera_id = camera_id
        speed = SpeedEstimator(roi.homography) if roi.homography else None
        self.ctx = RuleContext(
            camera_id=camera_id, fps=fps, thresholds=roi.thresholds, speed_estimator=speed
        )
        self.rules: list[Rule] = [LineCrossingRule(line) for line in roi.lines]
        for poly in roi.polygons:
            for rule_name in poly.rules:
                factory = _POLYGON_RULES[rule_name]
                try:
                    self.rules.append(factory(poly))
                except ValueError as e:
                    log.warning("[%s] skipping rule %s: %s", camera_id, rule_name, e)

    def process(self, frame: Frame, tracks: list[TrackedObject]) -> list[Event]:
        if self.ctx.speed_estimator is not None:
            active: set[int] = set()
            for t in tracks:
                t.speed_kmh = self.ctx.speed_estimator.update(
                    t.object_id, t.centroid, t.timestamp
                )
                active.add(t.object_id)
            self.ctx.speed_estimator.purge(active)

        events: list[Event] = []
        for rule in self.rules:
            events.extend(rule.process(frame, tracks, self.ctx))
        if events:
            snapshot = frame.image.copy()
            for e in events:
                if e.snapshot is None:
                    e.snapshot = snapshot
        return events
