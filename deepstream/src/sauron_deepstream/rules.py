from __future__ import annotations

import logging
import math
from collections import deque
from typing import Protocol

import numpy as np

from .domain import (
    Event,
    EventType,
    Frame,
    HomographyConfig,
    LineConfig,
    PolygonConfig,
    Priority,
    ROIConfig,
    ThresholdsConfig,
    TrackedObject,
)

log = logging.getLogger(__name__)


def _cross(point, start, end) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (
        end[1] - start[1]
    ) * (point[0] - start[0])


def _segments_cross(a, b, c, d) -> bool:
    return _cross(a, c, d) * _cross(b, c, d) < 0 and _cross(c, a, b) * _cross(d, a, b) < 0


def _inside(point: tuple[float, float], polygon: np.ndarray) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
        previous = current
    return inside


def _polygon_area(polygon: np.ndarray) -> float:
    x = polygon[:, 0]
    y = polygon[:, 1]
    return abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))) / 2


class SpeedEstimator:
    def __init__(self, config: HomographyConfig) -> None:
        rows: list[list[float]] = []
        for (x, y), (u, v) in zip(config.src_points, config.dst_points, strict=True):
            rows.extend(
                [
                    [-x, -y, -1, 0, 0, 0, u * x, u * y, u],
                    [0, 0, 0, -x, -y, -1, v * x, v * y, v],
                ]
            )
        _, _, vh = np.linalg.svd(np.asarray(rows, dtype=np.float64))
        self._matrix = vh[-1].reshape(3, 3)
        self._last: dict[int, tuple[float, np.ndarray]] = {}

    def update(self, track: TrackedObject) -> float | None:
        point = self._matrix @ np.array([*track.centroid, 1.0])
        world = point[:2] / point[2]
        previous = self._last.get(track.object_id)
        self._last[track.object_id] = (track.timestamp, world)
        if previous is None or track.timestamp - previous[0] <= 1e-3:
            return None
        return float(np.linalg.norm(world - previous[1])) / (track.timestamp - previous[0]) * 3.6

    def purge(self, active: set[int]) -> None:
        for object_id in set(self._last) - active:
            self._last.pop(object_id, None)


class _Rule(Protocol):
    def process(
        self, frame: Frame, tracks: list[TrackedObject], thresholds: ThresholdsConfig, fps: int
    ) -> list[Event]: ...


class _LineCrossing:
    def __init__(self, config: LineConfig) -> None:
        self.config = config
        self._last: dict[int, tuple[float, float]] = {}
        self._last_seen: dict[int, float] = {}
        self._counted: set[int] = set()

    def process(self, frame, tracks, thresholds, fps) -> list[Event]:
        events: list[Event] = []
        for track in tracks:
            self._last_seen[track.object_id] = frame.timestamp
            if self.config.classes and track.class_name not in self.config.classes:
                continue
            current = track.centroid
            previous = self._last.get(track.object_id)
            self._last[track.object_id] = current
            if previous is None or track.object_id in self._counted:
                continue
            if not _segments_cross(previous, current, *self.config.points):
                continue
            self._counted.add(track.object_id)
            direction = "forward" if _cross(previous, *self.config.points) < 0 else "reverse"
            if self.config.direction:
                movement = np.subtract(current, previous)
                direction = (
                    "forward"
                    if float(movement @ np.asarray(self.config.direction)) > 0
                    else "reverse"
                )
            events.append(
                Event(
                    EventType.LINE_CROSSING,
                    frame.camera_id,
                    frame.timestamp,
                    track.score,
                    Priority.INFO,
                    self.config.id,
                    track.object_id,
                    {
                        "line_id": self.config.id,
                        "vehicle_class": track.class_name,
                        "direction": direction,
                        "centroid": list(current),
                        "speed_kmh": round(track.speed_kmh, 1) if track.speed_kmh else None,
                    },
                )
            )
        stale = [
            object_id
            for object_id, last_seen in self._last_seen.items()
            if frame.timestamp - last_seen > 60
        ]
        for object_id in stale:
            self._last_seen.pop(object_id, None)
            self._last.pop(object_id, None)
            self._counted.discard(object_id)
        return events


class _Stopped:
    def __init__(self, config: PolygonConfig) -> None:
        self.config = config
        self.polygon = np.asarray(config.points, dtype=np.float64)
        self._since: dict[int, float] = {}
        self._alerted: set[int] = set()

    def process(self, frame, tracks, thresholds, fps) -> list[Event]:
        events: list[Event] = []
        active = {track.object_id for track in tracks}
        for object_id in set(self._since) - active:
            self._since.pop(object_id, None)
            self._alerted.discard(object_id)
        for track in tracks:
            stationary = math.hypot(*track.velocity) * fps < thresholds.stopped_speed_epsilon
            if not (_inside(track.centroid, self.polygon) and stationary):
                self._since.pop(track.object_id, None)
                self._alerted.discard(track.object_id)
                continue
            since = self._since.setdefault(track.object_id, frame.timestamp)
            duration = frame.timestamp - since
            if duration < thresholds.stopped_seconds or track.object_id in self._alerted:
                continue
            self._alerted.add(track.object_id)
            event_type = (
                EventType.OBSTRUCTION
                if self.config.kind == "parking"
                else EventType.STOPPED_VEHICLE
            )
            events.append(
                Event(
                    event_type,
                    frame.camera_id,
                    frame.timestamp,
                    track.score,
                    Priority.WARNING,
                    f"stopped:{self.config.id}",
                    track.object_id,
                    {
                        "polygon_id": self.config.id,
                        "vehicle_class": track.class_name,
                        "stopped_seconds": round(duration, 1),
                        "centroid": list(track.centroid),
                        "bbox": list(track.bbox),
                    },
                )
            )
        return events


class _WrongWay:
    def __init__(self, config: PolygonConfig) -> None:
        if config.direction is None:
            raise ValueError(f"polygon {config.id}: wrong_way requires direction")
        self.config = config
        self.polygon = np.asarray(config.points, dtype=np.float64)
        self.direction = np.asarray(config.direction, dtype=np.float64)
        self._samples: dict[int, deque[tuple[float, float]]] = {}
        self._alerted: set[int] = set()
        self._last_seen: dict[int, float] = {}

    def process(self, frame, tracks, thresholds, fps) -> list[Event]:
        events: list[Event] = []
        for track in tracks:
            self._last_seen[track.object_id] = frame.timestamp
            if not _inside(track.centroid, self.polygon) or len(track.track_history) < 2:
                self._samples.pop(track.object_id, None)
                self._alerted.discard(track.object_id)
                continue
            window = min(len(track.track_history), max(2, fps // 2))
            movement = np.subtract(track.track_history[-1], track.track_history[-window])
            norm = float(np.linalg.norm(movement) * np.linalg.norm(self.direction))
            if norm <= 2.0:
                continue
            cosine = float(movement @ self.direction) / norm
            samples = self._samples.setdefault(track.object_id, deque(maxlen=fps * 10))
            samples.append((frame.timestamp, cosine))
            recent = [item for item in samples if frame.timestamp - item[0] <= thresholds.wrong_way_seconds]
            span = recent[-1][0] - recent[0][0]
            if (
                track.object_id not in self._alerted
                and span >= thresholds.wrong_way_seconds
                and all(value < thresholds.wrong_way_cosine for _, value in recent)
            ):
                self._alerted.add(track.object_id)
                events.append(
                    Event(
                        EventType.WRONG_WAY,
                        frame.camera_id,
                        frame.timestamp,
                        track.score,
                        Priority.CRITICAL,
                        f"wrong-way:{self.config.id}",
                        track.object_id,
                        {
                            "polygon_id": self.config.id,
                            "vehicle_class": track.class_name,
                            "cosine": round(cosine, 3),
                            "sustained_seconds": round(span, 1),
                            "centroid": list(track.centroid),
                        },
                    )
                )
        stale = [
            object_id
            for object_id, last_seen in self._last_seen.items()
            if frame.timestamp - last_seen > 60
        ]
        for object_id in stale:
            self._last_seen.pop(object_id, None)
            self._samples.pop(object_id, None)
            self._alerted.discard(object_id)
        return events


class _Congestion:
    def __init__(self, config: PolygonConfig) -> None:
        self.config = config
        self.polygon = np.asarray(config.points, dtype=np.float64)
        self.area = _polygon_area(self.polygon)
        self._since: float | None = None
        self._last_alert = float("-inf")

    def process(self, frame, tracks, thresholds, fps) -> list[Event]:
        selected = [track for track in tracks if _inside(track.centroid, self.polygon)]
        covered = sum(
            max(0.0, track.bbox[2] - track.bbox[0])
            * max(0.0, track.bbox[3] - track.bbox[1])
            for track in selected
        )
        occupancy = min(1.0, covered / self.area) if self.area > 0 else 0.0
        if occupancy < thresholds.congestion_occupancy:
            self._since = None
            return []
        self._since = frame.timestamp if self._since is None else self._since
        duration = frame.timestamp - self._since
        if duration < thresholds.congestion_seconds:
            return []
        if frame.timestamp - self._last_alert < thresholds.congestion_cooldown_s:
            return []
        self._last_alert = frame.timestamp
        self._since = None
        return [
            Event(
                EventType.CONGESTION,
                frame.camera_id,
                frame.timestamp,
                occupancy,
                Priority.WARNING,
                f"congestion:{self.config.id}",
                metadata={
                    "polygon_id": self.config.id,
                    "occupancy": round(occupancy, 3),
                    "sustained_seconds": round(duration, 1),
                    "vehicles_in_roi": len(selected),
                },
            )
        ]


class RulesEngine:
    """Zero-copy traffic analytics over NvDCF tracks."""

    def __init__(self, camera_id: str, roi: ROIConfig, fps: int = 15) -> None:
        self.camera_id = camera_id
        self.fps = fps
        self.thresholds = roi.thresholds
        self.speed = SpeedEstimator(roi.homography) if roi.homography else None
        self.rules: list[_Rule] = [_LineCrossing(config) for config in roi.lines]
        factories = {"stopped": _Stopped, "wrong_way": _WrongWay, "congestion": _Congestion}
        for polygon in roi.polygons:
            for name in polygon.rules:
                factory = factories.get(name)
                if factory is None:
                    log.warning("[%s] rule %s is not supported by the traffic plane", camera_id, name)
                    continue
                try:
                    self.rules.append(factory(polygon))
                except ValueError as error:
                    log.warning("[%s] skipping %s: %s", camera_id, name, error)

    def process(self, frame: Frame, tracks: list[TrackedObject]) -> list[Event]:
        if self.speed:
            active = {track.object_id for track in tracks}
            for track in tracks:
                track.speed_kmh = self.speed.update(track)
            self.speed.purge(active)
        events: list[Event] = []
        for rule in self.rules:
            events.extend(rule.process(frame, tracks, self.thresholds, self.fps))
        return events
