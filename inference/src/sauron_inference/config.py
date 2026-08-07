from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from .models import DEFAULT_MODEL, validate_model

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
    use_gstreamer: bool = True
    # GStreamer H.264 decoder element: nvv4l2decoder (DeepStream/JetPack),
    # nvdec / nvh264dec (GStreamer nvcodec), or avdec_h264 (software).
    decoder: str = "nvv4l2decoder"


class ClipConfig(BaseModel):
    """Pre-event video clip evidence (MP4 ring buffer per stream)."""

    enabled: bool = False
    preroll_seconds: float = 8.0
    jpeg_quality: int = 75
    clip_fps: int = 12


class OpenAIDetectorConfig(BaseModel):
    """Remote inference via an OpenAI-compatible vision endpoint (chat.completions).

    Works with vLLM, Ollama, llama.cpp server, OpenAI, etc. — local or remote.
    """

    base_url: str = "http://localhost:11434/v1"
    model: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    # API key is read from this env var; never stored in YAML.
    api_key_env: str = "OPENAI_API_KEY"
    timeout_s: float = 20.0
    max_image_side: int = 960


class DetectorConfig(BaseModel):
    backend: Literal["tensorrt", "onnx", "openai", "mock", "pose", "pose_objects"] = "tensorrt"
    openai: OpenAIDetectorConfig = Field(default_factory=OpenAIDetectorConfig)


class DefaultsConfig(BaseModel):
    model: str = DEFAULT_MODEL  # model catalog name; override per stream
    # pose backends: pose model (people + keypoints) + objects model (chairs etc)
    pose_onnx_path: str = "models/yolov8n-pose.onnx"
    objects_onnx_path: str = "models/yolov8n.onnx"
    input_size: tuple[int, int] = (640, 640)
    confidence_threshold: float = 0.5
    nms_threshold: float = 0.45
    detector: DetectorConfig = Field(default_factory=DetectorConfig)
    classes: dict[int, str] = Field(
        default_factory=lambda: {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
    )
    tracker: TrackerConfig = Field(default_factory=TrackerConfig)
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    clips: ClipConfig = Field(default_factory=ClipConfig)

    @field_validator("model")
    @classmethod
    def _known_model(cls, v: str) -> str:
        return validate_model(v)


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


PolygonRuleName = Literal["stopped", "wrong_way", "congestion", "occupancy", "grouping", "chair_occupancy"]


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
    occupancy_interval_s: float = 30.0


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
    model: str | None = None
    pose_onnx_path: str | None = None
    objects_onnx_path: str | None = None
    confidence_threshold: float | None = None
    width: int = 1280
    height: int = 720
    roi: ROIConfig | None = None
    detector: DetectorConfig | None = None

    @field_validator("model")
    @classmethod
    def _known_model(cls, v: str | None) -> str | None:
        return validate_model(v) if v is not None else v

    def resolved_detector(self, defaults: DefaultsConfig) -> DetectorConfig:
        return self.detector or defaults.detector

    def resolved_model(self, defaults: DefaultsConfig) -> str:
        return self.model or defaults.model

    def resolved_pose_onnx(self, defaults: DefaultsConfig) -> str:
        return self.pose_onnx_path or defaults.pose_onnx_path

    def resolved_objects_onnx(self, defaults: DefaultsConfig) -> str:
        return self.objects_onnx_path or defaults.objects_onnx_path

    def resolved_confidence(self, defaults: DefaultsConfig) -> float:
        return (
            self.confidence_threshold
            if self.confidence_threshold is not None
            else defaults.confidence_threshold
        )


class AppConfig(BaseModel):
    name: str = "sauron"
    # Event sinks; env vars SAURON_REDIS_URL / SAURON_API_INGEST_URL take precedence.
    redis_url: str | None = None
    api_ingest_url: str | None = None


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
