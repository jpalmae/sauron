from __future__ import annotations

import math
from collections import Counter

import cv2
import numpy as np

from ..config import PolygonConfig
from ..types import Frame, TrackedObject
from .base import Rule, RuleContext
from .events import Event, EventType, Priority
from .geometry import point_in_polygon

_POSTURE_STABLE_FRAMES = 4
_KPT_CONF = 0.3
_KNEE_BEND_DEG = 140.0
_FALLEN_ASPECT = 1.3  # bbox width/height >= this => lying down
_REID_SIM = 0.55  # color-histogram cosine sim above this => same person
_FALL_COOLDOWN_S = 20.0


def _angle(vertex, a, b) -> float:
    v1 = (a[0] - vertex[0], a[1] - vertex[1])
    v2 = (b[0] - vertex[0], b[1] - vertex[1])
    denom = math.hypot(*v1) * math.hypot(*v2) + 1e-6
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / denom))
    return math.degrees(cos)


def classify_posture(keypoints: np.ndarray | None, bbox) -> str:
    """keypoints [17,3] + xyxy bbox -> standing | sitting | fallen | unknown."""
    if bbox is None:
        return "unknown"
    try:
        x1, y1, x2, y2 = bbox
        w = x2 - x1
        h = y2 - y1
        if h > 0 and w / h >= _FALLEN_ASPECT:
            return "fallen"
    except Exception:
        pass
    if keypoints is None:
        return "unknown"
    kp = np.asarray(keypoints)
    try:
        angles = []
        for hip_i, knee_i, ankle_i in [(11, 13, 15), (12, 14, 16)]:
            hc = kp[hip_i][2]
            kc = kp[knee_i][2]
            ac = kp[ankle_i][2]
            if hc >= _KPT_CONF and kc >= _KPT_CONF and ac >= _KPT_CONF:
                angles.append(_angle(tuple(kp[knee_i][:2]), tuple(kp[hip_i][:2]), tuple(kp[ankle_i][:2])))
        if not angles:
            return "unknown"
        avg = sum(angles) / len(angles)
        return "sitting" if avg < _KNEE_BEND_DEG else "standing"
    except Exception:
        return "unknown"


def _fingerprint(image: np.ndarray, bbox) -> np.ndarray | None:
    try:
        x1, y1, x2, y2 = [int(v) for v in bbox]
        h, w = image.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 - x1 < 8 or y2 - y1 < 8:
            return None
        crop = image[y1:y2, x1:x2]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
        cv2.normalize(hist, hist)
        return hist.flatten()
    except Exception:
        return None


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b)) + 1e-6
    return float(np.dot(a, b) / denom)


class OccupancyRule(Rule):
    """People/space occupancy + posture + fall + ReID analytics."""

    def __init__(self, cfg: PolygonConfig) -> None:
        self.cfg = cfg
        self.rule_id = f"occupancy:{cfg.id}"
        self._polygon = np.array(cfg.points, dtype=np.float32)
        self._last_emit: float = float("-inf")
        self._seen: set[int] = set()
        self._first_seen: dict[int, float] = {}
        self._peak: int = 0
        self._committed: dict[int, str] = {}
        self._pending: dict[int, tuple[str, int]] = {}
        self._last_fall: dict[int, float] = {}
        self.sit_to_stand = 0
        self.stand_to_sit = 0
        self.falls = 0
        self._gallery: list[np.ndarray] = []  # ReID color fingerprints
        self.unique_reid = 0

    def _inside_people(self, tracks: list[TrackedObject]) -> list[TrackedObject]:
        return [
            t for t in tracks
            if t.class_name == "person" and point_in_polygon(t.centroid, self._polygon)
        ]

    def _register_reid(self, oid: int, t: TrackedObject, frame: Frame) -> None:
        fp = _fingerprint(frame.image, t.bbox)
        if fp is None:
            return
        best = max((_cosine(fp, g) for g in self._gallery), default=0.0)
        if best < _REID_SIM:
            self._gallery.append(fp)
            self.unique_reid += 1

    def _update_posture(self, oid: int, raw: str, frame: Frame) -> list[tuple[int, str, str]]:
        """Anti-flicker state machine; returns committed transitions this frame."""
        transitions: list[tuple[int, str, str]] = []
        committed = self._committed.get(oid)
        if committed is None:
            self._committed[oid] = raw
            self._pending.pop(oid, None)
            return transitions
        if raw == committed:
            self._pending.pop(oid, None)
            return transitions
        cand, n = self._pending.get(oid, (raw, 0))
        cand = raw if cand != raw else cand
        n = n + 1 if cand == raw else 1
        self._pending[oid] = (cand, n)
        if n >= _POSTURE_STABLE_FRAMES:
            transitions.append((oid, committed, cand))
            if committed == "sitting" and cand == "standing":
                self.sit_to_stand += 1
            elif committed == "standing" and cand == "sitting":
                self.stand_to_sit += 1
            self._committed[oid] = cand
            self._pending.pop(oid, None)
        return transitions

    def process(self, frame: Frame, tracks: list[TrackedObject], ctx: RuleContext) -> list[Event]:
        now = frame.timestamp
        inside = self._inside_people(tracks)
        inside_ids = {t.object_id for t in inside}

        events: list[Event] = []

        for t in inside:
            if t.object_id not in self._first_seen:
                self._first_seen[t.object_id] = now
                self._seen.add(t.object_id)
                self._register_reid(t.object_id, t, frame)
            for oid, frm, to in self._update_posture(
                t.object_id, classify_posture(t.keypoints, t.bbox), frame
            ):
                if to == "fallen" and now - self._last_fall.get(oid, 0.0) > _FALL_COOLDOWN_S:
                    self._last_fall[oid] = now
                    self.falls += 1
                    events.append(
                        Event(
                            event_type=EventType.FALL,
                            camera_id=ctx.camera_id,
                            timestamp=now,
                            confidence=1.0,
                            priority=Priority.CRITICAL,
                            rule_id=f"fall:{self.cfg.id}",
                            object_id=oid,
                            metadata={"polygon_id": self.cfg.id, "from": frm, "to": to},
                        )
                    )

        for oid in list(self._first_seen):
            if oid not in inside_ids:
                self._first_seen.pop(oid, None)
                self._committed.pop(oid, None)
                self._pending.pop(oid, None)

        count = len(inside)
        if count > self._peak:
            self._peak = count

        if now - self._last_emit < ctx.thresholds.occupancy_interval_s:
            return events
        self._last_emit = now

        avg_dwell = (
            sum(now - self._first_seen[t.object_id] for t in inside) / count if count else 0.0
        )
        posture = Counter(self._committed.get(t.object_id, "unknown") for t in inside)

        events.append(
            Event(
                event_type=EventType.OCCUPANCY,
                camera_id=ctx.camera_id,
                timestamp=now,
                confidence=1.0,
                priority=Priority.INFO,
                rule_id=self.rule_id,
                metadata={
                    "polygon_id": self.cfg.id,
                    "count": count,
                    "by_class": {"person": count},
                    "unique_total": len(self._seen),
                    "unique_reid": self.unique_reid,
                    "avg_dwell_s": round(avg_dwell, 1),
                    "peak": self._peak,
                    "posture": {
                        "standing": posture.get("standing", 0),
                        "sitting": posture.get("sitting", 0),
                        "fallen": posture.get("fallen", 0),
                        "unknown": posture.get("unknown", 0),
                    },
                    "sit_to_stand": self.sit_to_stand,
                    "stand_to_sit": self.stand_to_sit,
                    "transitions": self.sit_to_stand + self.stand_to_sit,
                    "falls": self.falls,
                },
            )
        )
        return events
