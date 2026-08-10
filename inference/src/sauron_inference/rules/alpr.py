from __future__ import annotations

import logging

from ..alpr.crop import alpr_crop
from ..alpr.ocr import OcrBackend, normalize_plate
from ..config import AlprConfig
from ..types import Frame, TrackedObject
from .base import Rule, RuleContext
from .events import Event, EventType, Priority

log = logging.getLogger(__name__)


class AlprRule(Rule):
    """License plate reading on vehicle tracks (camera-level rule).

    OCRs each vehicle track throttled to every N frames; emits ALPR when a
    plate is read with enough confidence. Watchlist plates escalate to
    critical ALPR_WATCHLIST alerts.
    """

    def __init__(self, cfg: AlprConfig, ocr: OcrBackend) -> None:
        self.cfg = cfg
        self.ocr = ocr
        self.rule_id = "alpr"
        self._watchlist = {normalize_plate(p) for p in cfg.watchlist}
        self._last_ocr_frame: dict[int, int] = {}
        self._read_by_track: dict[int, str] = {}

    def process(
        self, frame: Frame, tracks: list[TrackedObject], ctx: RuleContext
    ) -> list[Event]:
        events: list[Event] = []
        for track in tracks:
            oid = track.object_id
            crop = alpr_crop(frame.image, track)
            if crop is None:
                continue
            last = self._last_ocr_frame.get(oid)
            if oid in self._read_by_track:
                continue
            if last is not None and frame.seq - last < self.cfg.ocr_interval_frames:
                continue
            self._last_ocr_frame[oid] = frame.seq
            plate, conf = self.ocr.read_plate(crop)
            if not plate or conf < self.cfg.min_confidence:
                continue
            self._read_by_track[oid] = plate
            on_watchlist = plate in self._watchlist
            events.append(
                Event(
                    event_type=EventType.ALPR_WATCHLIST if on_watchlist else EventType.ALPR,
                    camera_id=ctx.camera_id,
                    timestamp=track.timestamp,
                    confidence=conf,
                    priority=Priority.CRITICAL if on_watchlist else Priority.INFO,
                    rule_id=self.rule_id,
                    object_id=oid,
                    metadata={
                        "plate_text": plate,
                        "ocr_confidence": round(conf, 3),
                        "vehicle_class": track.class_name,
                        "watchlist": on_watchlist,
                        "speed_kmh": (
                            round(track.speed_kmh, 1) if track.speed_kmh else None
                        ),
                    },
                )
            )
        return events
