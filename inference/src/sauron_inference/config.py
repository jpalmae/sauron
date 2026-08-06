from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

Point = tuple[float, float]


class TrackerConfig(BaseModel):
    high_thresh: float = 0.5
    low_thresh: float = 0.1
    match_thresh: float = 0.8
    max_time_lost: int = 30
    history_size: int = 60

    @field_validator("high_thresh", "low_thresh", "match_thresh")
    @classmethod
    def _in_unit_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("tracker thresholds must be within [0, 1]")
        return v


class CaptureConfig(BaseModel):
    latency_ms: int = 200
    reconnect_backoff_s: float = 2.0
    queue_size: int = 2


class DefaultsConfig(BaseModel):
    engine_path: str = "models/yolov8n_fp16.engine"
    input_size: tuple[int, int] = (640, 640)
    confidence_threshold: float = 0.5
    nms_threshold: float = 0.45
    classes: dict[int, str] = Field(
        default_factory=lambda: {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
    )
    tracker: TrackerConfig = Field(default_factory=TrackerConfig)
    capture: CaptureConfig = Field(default_factory=CaptureConfig)


class LineConfig(BaseModel):
    id: str
    points: list[Point]
    # Counting direction; crossings against it are tagged "reverse".
    direction: Point | None = None
    classes: list[str] | None = None

    @field_validator("points")
    @classmethod
    def _two_points(cls, v: list[Point]) -> list[Point]:
        if len(v) != 2:
            raise ValueError("a crossing line needs exactly 2 points")
        return v


PolygonRuleName = Literal["stopped", "wrong_way", "congestion"]


def _default_polygon_rules() -> list[PolygonRuleName]:
    return ["stopped"]


class PolygonConfig(BaseModel):
    id: str
    points: list[Point]
    kind: Literal["lane", "parking", "counting"] = "lane"
    # Which rules evaluate this polygon.
    rules: list[PolygonRuleName] = Field(default_factory=_default_polygon_rules)
    # Allowed traffic direction vector (required for wrong_way).
    direction: Point | None = None

    @field_validator("points")
    @classmethod
    def _at_least_three(cls, v: list[Point]) -> list[Point]:
        if len(v) < 3:
            raise ValueError("a polygon needs at least 3 points")
        return v


class HomographyConfig(BaseModel):
    """Pixel -> ground plane (meters) calibration, >= 4 point pairs."""

    src_points: list[Point]
    dst_points: list[Point]

    @field_validator("dst_points")
    @classmethod
    def _same_length(cls, v: list[Point], info) -> list[Point]:
        src = info.data.get("src_points", [])
        if len(v) != len(src) or len(v) < 4:
            raise ValueError("homography needs >= 4 src/dst point pairs of equal length")
        return v


class ThresholdsConfig(BaseModel):
    stopped_seconds: float = 15.0
    stopped_speed_epsilon: float = 3.0  # px/s
    wrong_way_cosine: float = -0.7
    wrong_way_seconds: float = 3.0
    congestion_occupancy: float = 0.6  # fraction of polygon area
    congestion_seconds: float = 30.0
    congestion_cooldown_s: float = 60.0


class ROIConfig(BaseModel):
    lines: list[LineConfig] = Field(default_factory=list)
    polygons: list[PolygonConfig] = Field(default_factory=list)
    homography: HomographyConfig | None = None
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)


class StreamConfig(BaseModel):
    id: str
    name: str = ""
    type: Literal["rtsp", "file", "synthetic"] = "rtsp"
    source: str
    device_id: int | None = None
    target_fps: int = 15
    engine_path: str | None = None
    confidence_threshold: float | None = None
    width: int = 1280
    height: int = 720
    roi: ROIConfig | None = None

    def resolved_engine(self, defaults: DefaultsConfig) -> str:
        return self.engine_path or defaults.engine_path

    def resolved_confidence(self, defaults: DefaultsConfig) -> float:
        return (
            self.confidence_threshold
            if self.confidence_threshold is not None
            else defaults.confidence_threshold
        )


class AppConfig(BaseModel):
    name: str = "sauron"


class PipelineConfig(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    devices: list[int] = Field(default_factory=lambda: [0])
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    streams: list[StreamConfig]

    @field_validator("streams")
    @classmethod
    def _unique_ids(cls, v: list[StreamConfig]) -> list[StreamConfig]:
        ids = [s.id for s in v]
        if len(ids) != len(set(ids)):
            raise ValueError("stream ids must be unique")
        return v

    def device_for(self, index: int, stream: StreamConfig) -> int:
        if stream.device_id is not None:
            return stream.device_id
        return self.devices[index % len(self.devices)]


def load_config(path: str | Path) -> PipelineConfig:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return PipelineConfig.model_validate(raw)
