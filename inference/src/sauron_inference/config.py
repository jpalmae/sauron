from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


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
