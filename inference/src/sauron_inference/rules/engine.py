from __future__ import annotations

import logging
from collections.abc import Callable

from ..config import PolygonConfig, PolygonRuleName, ROIConfig
from ..types import Frame, TrackedObject
from .alpr import AlprRule
from .base import Rule, RuleContext
from .chair_occupancy import ChairOccupancyRule
from .congestion import CongestionRule
from .events import Event, EventType, Priority
from .grouping import GroupingRule
from .line_crossing import LineCrossingRule
from .occupancy import OccupancyRule
from .speed import SpeedEstimator
from .stopped_vehicle import StoppedVehicleRule
from .wrong_way import WrongWayRule

log = logging.getLogger(__name__)

_POLYGON_RULES: dict[PolygonRuleName, Callable[[PolygonConfig], Rule]] = {
    "stopped": StoppedVehicleRule,
    "wrong_way": WrongWayRule,
    "congestion": CongestionRule,
    "occupancy": OccupancyRule,
    "grouping": GroupingRule,
    "chair_occupancy": ChairOccupancyRule,
}


class RulesEngine:
    """Per-camera dispatcher: evaluates configured rules over tracked objects."""

    def __init__(
        self,
        camera_id: str,
        roi: ROIConfig,
        fps: int = 15,
        *,
        attach_visual_evidence: bool = True,
    ) -> None:
        self.camera_id = camera_id
        self.privacy = roi.privacy
        self.attach_visual_evidence = attach_visual_evidence
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
        if roi.alpr is not None and roi.alpr.enabled:
            from ..alpr.ocr import build_ocr

            self.rules.append(AlprRule(roi.alpr, build_ocr(roi.alpr.backend)))
            log.info("[%s] ALPR enabled (%s)", camera_id, roi.alpr.backend)

    def process(self, frame: Frame, tracks: list[TrackedObject]) -> list[Event]:
        if self.ctx.speed_estimator is not None:
            active: set[int] = set()
            for t in tracks:
                t.speed_kmh = self.ctx.speed_estimator.update(t.object_id, t.centroid, t.timestamp)
                active.add(t.object_id)
            self.ctx.speed_estimator.purge(active)

        events: list[Event] = []
        for rule in self.rules:
            events.extend(rule.process(frame, tracks, self.ctx))
        evidence_events = [
            event
            for event in events
            if event.priority in (Priority.WARNING, Priority.CRITICAL)
            or event.event_type
            in (EventType.LINE_CROSSING, EventType.ALPR, EventType.ALPR_WATCHLIST)
        ]
        if evidence_events and self.attach_visual_evidence:
            self._attach_signatures(events, frame, tracks)
            if self.privacy is not None:
                from .privacy import redact_frame

                snapshot = redact_frame(frame.image, tracks, self.privacy)
            else:
                snapshot = frame.image.copy()
            for e in evidence_events:
                if e.snapshot is None:
                    e.snapshot = snapshot
        return events

    @staticmethod
    def _attach_signatures(events: list[Event], frame: Frame, tracks: list[TrackedObject]) -> None:
        """Appearance signature on line-crossing events (multi-camera ReID)."""
        from .events import EventType
        from .signature import hsv_signature

        by_id = {t.object_id: t for t in tracks}
        for e in events:
            if e.event_type != EventType.LINE_CROSSING or e.object_id is None:
                continue
            track = by_id.get(e.object_id)
            if track is None:
                continue
            sig = hsv_signature(frame.image, track.bbox)
            if sig:
                e.metadata["signature"] = sig
