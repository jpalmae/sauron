from __future__ import annotations

import logging
import os
import time

from ..bridge.http_publisher import HTTPEventPublisher
from ..bridge.redis_publisher import RedisEventPublisher
from ..capture.base import FrameSource
from ..capture.rtsp import RTSPSource
from ..capture.synthetic import FileSource, SyntheticSource
from ..config import PipelineConfig, StreamConfig
from ..detection.base import Detector
from ..detection.mock import MockDetector
from ..detection.onnx_dnn import OnnxDnnDetector
from ..detection.openai_compat import OpenAICompatDetector
from ..detection.tensorrt_yolo import TensorRTYolo
from ..metrics import StreamMetrics
from ..models import engine_path, onnx_path
from ..rules.engine import RulesEngine
from ..rules.events import Event
from ..tracking.bytetrack import BYTETracker
from .clip import ClipBuffer
from .stream import EventCallback, NullCallback, StreamPipeline, TracksCallback

log = logging.getLogger(__name__)


def build_source(stream: StreamConfig, cfg: PipelineConfig) -> FrameSource:
    if stream.type == "synthetic":
        return SyntheticSource(
            camera_id=stream.id,
            width=stream.width,
            height=stream.height,
            target_fps=stream.target_fps,
        )
    if stream.type == "file":
        return FileSource(camera_id=stream.id, path=stream.source, target_fps=stream.target_fps)
    return RTSPSource(
        camera_id=stream.id,
        url=stream.source,
        cfg=cfg.defaults.capture,
        use_gstreamer=cfg.defaults.capture.use_gstreamer,
        decoder=cfg.defaults.capture.decoder,
        target_fps=stream.target_fps,
    )


def build_detector(stream: StreamConfig, cfg: PipelineConfig, device_id: int) -> Detector:
    det_cfg = stream.resolved_detector(cfg.defaults)
    conf = stream.resolved_confidence(cfg.defaults)
    if det_cfg.backend == "mock":
        return MockDetector(classes=cfg.defaults.classes, conf_threshold=conf)
    if det_cfg.backend == "onnx":
        return OnnxDnnDetector(
            onnx_path=onnx_path(stream.resolved_model(cfg.defaults)),
            input_size=cfg.defaults.input_size,
            conf_threshold=conf,
            nms_threshold=cfg.defaults.nms_threshold,
            classes=cfg.defaults.classes,
        )
    if det_cfg.backend == "openai":
        return OpenAICompatDetector(
            det_cfg.openai, classes=cfg.defaults.classes, conf_threshold=conf
        )
    return TensorRTYolo(
        engine_path=engine_path(stream.resolved_model(cfg.defaults)),
        device_id=device_id,
        input_size=cfg.defaults.input_size,
        conf_threshold=conf,
        nms_threshold=cfg.defaults.nms_threshold,
        classes=cfg.defaults.classes,
    )


class PipelineManager:
    """Builds and supervises one StreamPipeline per configured stream."""

    def __init__(
        self,
        cfg: PipelineConfig,
        on_tracks: TracksCallback | None = None,
        on_event: EventCallback | None = None,
        detector_factory=build_detector,
        source_factory=build_source,
    ) -> None:
        self.cfg = cfg
        self.on_tracks = on_tracks or NullCallback()
        self._user_on_event = on_event
        self.on_event = self._build_event_sink()
        self._detector_factory = detector_factory
        self._source_factory = source_factory
        self.pipelines: list[StreamPipeline] = []
        self.metrics = StreamMetrics()

    def _build_event_sink(self) -> EventCallback | None:
        sinks: list[EventCallback] = []
        if self._user_on_event is not None:
            sinks.append(self._user_on_event)
        redis_url = os.environ.get("SAURON_REDIS_URL") or self.cfg.app.redis_url
        api_url = os.environ.get("SAURON_API_INGEST_URL") or self.cfg.app.api_ingest_url
        if redis_url:
            sinks.append(RedisEventPublisher(redis_url))
            log.info("events will be published to redis: %s", redis_url)
        if api_url:
            sinks.append(HTTPEventPublisher(api_url))
            log.info("events will be posted to api: %s", api_url)
        if not sinks:
            return None

        def emit(event: Event) -> None:
            for sink in sinks:
                try:
                    sink(event)
                except Exception:
                    log.exception("event sink failed")

        return emit

    def build(self) -> None:
        for i, stream in enumerate(self.cfg.streams):
            device_id = self.cfg.device_for(i, stream)
            source = self._source_factory(stream, self.cfg)
            detector = self._detector_factory(stream, self.cfg, device_id)
            tracker = BYTETracker(self.cfg.defaults.tracker, frame_rate=stream.target_fps)
            engine = (
                RulesEngine(stream.id, stream.roi, fps=stream.target_fps)
                if stream.roi
                else None
            )
            clip_cfg = self.cfg.defaults.clips
            clip_buffer = (
                ClipBuffer(
                    preroll_seconds=clip_cfg.preroll_seconds,
                    fps=stream.target_fps,
                    jpeg_quality=clip_cfg.jpeg_quality,
                    clip_fps=clip_cfg.clip_fps,
                )
                if clip_cfg.enabled
                else None
            )
            self.pipelines.append(
                StreamPipeline(
                    source=source,
                    detector=detector,
                    tracker=tracker,
                    on_tracks=self.on_tracks,
                    rules_engine=engine,
                    on_event=self.on_event,
                    clip_buffer=clip_buffer,
                    queue_size=self.cfg.defaults.capture.queue_size,
                    metrics=self.metrics,
                )
            )
            log.info("stream %s assigned to GPU %d", stream.id, device_id)

    def start(self) -> None:
        if not self.pipelines:
            self.build()
        for p in self.pipelines:
            p.start()
        log.info("started %d stream pipelines", len(self.pipelines))

    def stop(self) -> None:
        for p in self.pipelines:
            p.stop()
        log.info("all pipelines stopped")

    def run_forever(self) -> None:
        self.start()
        try:
            while True:
                time.sleep(10)
                for p in self.pipelines:
                    self.metrics.sync_counters(
                        p.source.camera_id, p.frames_captured, p.frames_dropped
                    )
                dead = [p.source.camera_id for p in self.pipelines if not p.alive]
                if dead:
                    log.warning("dead pipelines: %s", dead)
        except KeyboardInterrupt:
            log.info("shutting down")
        finally:
            self.stop()
