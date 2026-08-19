from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Point = tuple[float, float]
PolygonRuleName = Literal[
    "stopped",
    "wrong_way",
    "congestion",
    "occupancy",
    "grouping",
    "chair_occupancy",
]


def _default_polygon_rules() -> list[PolygonRuleName]:
    return ["stopped"]


class LineConfig(BaseModel):
    id: str
    points: list[Point]
    direction: Point | None = None
    classes: list[str] | None = None

    @field_validator("points")
    @classmethod
    def _two_points(cls, value: list[Point]) -> list[Point]:
        if len(value) != 2:
            raise ValueError("a crossing line needs exactly two points")
        return value


class PolygonConfig(BaseModel):
    id: str
    points: list[Point]
    kind: Literal["lane", "parking", "counting"] = "lane"
    rules: list[PolygonRuleName] = Field(default_factory=_default_polygon_rules)
    direction: Point | None = None

    @field_validator("points")
    @classmethod
    def _polygon(cls, value: list[Point]) -> list[Point]:
        if len(value) < 3:
            raise ValueError("a polygon needs at least three points")
        return value


class HomographyConfig(BaseModel):
    src_points: list[Point]
    dst_points: list[Point]

    @field_validator("dst_points")
    @classmethod
    def _matching_points(cls, value: list[Point], info) -> list[Point]:
        source = info.data.get("src_points", [])
        if len(value) != len(source) or len(value) < 4:
            raise ValueError("homography needs at least four matching point pairs")
        return value


class ThresholdsConfig(BaseModel):
    stopped_seconds: float = 15.0
    stopped_speed_epsilon: float = 3.0
    wrong_way_cosine: float = -0.7
    wrong_way_seconds: float = 3.0
    congestion_occupancy: float = 0.6
    congestion_seconds: float = 30.0
    congestion_cooldown_s: float = 60.0
    occupancy_interval_s: float = 30.0


class ROIConfig(BaseModel):
    lines: list[LineConfig] = Field(default_factory=list)
    polygons: list[PolygonConfig] = Field(default_factory=list)
    homography: HomographyConfig | None = None
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    # Accepted for API compatibility. Pixel-based ALPR/privacy are deliberately
    # outside this zero-copy traffic plane.
    alpr: dict[str, Any] | None = None
    privacy: dict[str, Any] | None = None


@dataclass(slots=True)
class Frame:
    camera_id: str
    seq: int
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class TrackedObject:
    object_id: int
    camera_id: str
    class_name: str
    class_id: int
    bbox: tuple[float, float, float, float]
    score: float
    centroid: tuple[float, float]
    velocity: tuple[float, float]
    track_history: list[tuple[float, float]]
    frame_seq: int
    timestamp: float
    speed_kmh: float | None = None


class EventType(StrEnum):
    LINE_CROSSING = "LINE_CROSSING"
    STOPPED_VEHICLE = "STOPPED_VEHICLE"
    OBSTRUCTION = "OBSTRUCTION"
    WRONG_WAY = "WRONG_WAY"
    CONGESTION = "CONGESTION"
    OCCUPANCY = "OCCUPANCY"


class Priority(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(slots=True)
class Event:
    event_type: EventType
    camera_id: str
    timestamp: float
    confidence: float
    priority: Priority
    rule_id: str
    object_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": str(self.event_type),
            "camera_id": self.camera_id,
            "timestamp": self.timestamp,
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.timestamp)),
            "confidence": round(self.confidence, 4),
            "priority": str(self.priority),
            "rule_id": self.rule_id,
            "object_id": self.object_id,
            "metadata": self.metadata,
        }
