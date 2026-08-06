from __future__ import annotations

import logging
import time

from ..capture.base import FrameSource
from ..capture.rtsp import RTSPSource
from ..capture.synthetic import FileSource, SyntheticSource
from ..config import PipelineConfig, StreamConfig
from ..detection.base import Detector
from ..detection.tensorrt_yolo import TensorRTYolo
from ..tracking.bytetrack import BYTETracker
from .stream import NullCallback, StreamPipeline, TracksCallback

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
        target_fps=stream.target_fps,
    )


def build_detector(stream: StreamConfig, cfg: PipelineConfig, device_id: int) -> Detector:
    return TensorRTYolo(
        engine_path=stream.resolved_engine(cfg.defaults),
        device_id=device_id,
        input_size=cfg.defaults.input_size,
        conf_threshold=stream.resolved_confidence(cfg.defaults),
        nms_threshold=cfg.defaults.nms_threshold,
        classes=cfg.defaults.classes,
    )


class PipelineManager:
    """Builds and supervises one StreamPipeline per configured stream."""

    def __init__(
        self,
        cfg: PipelineConfig,
        on_tracks: TracksCallback | None = None,
        detector_factory=build_detector,
        source_factory=build_source,
    ) -> None:
        self.cfg = cfg
        self.on_tracks = on_tracks or NullCallback()
        self._detector_factory = detector_factory
        self._source_factory = source_factory
        self.pipelines: list[StreamPipeline] = []

    def build(self) -> None:
        for i, stream in enumerate(self.cfg.streams):
            device_id = self.cfg.device_for(i, stream)
            source = self._source_factory(stream, self.cfg)
            detector = self._detector_factory(stream, self.cfg, device_id)
            tracker = BYTETracker(self.cfg.defaults.tracker, frame_rate=stream.target_fps)
            self.pipelines.append(
                StreamPipeline(
                    source=source,
                    detector=detector,
                    tracker=tracker,
                    on_tracks=self.on_tracks,
                    queue_size=self.cfg.defaults.capture.queue_size,
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
                dead = [p.source.camera_id for p in self.pipelines if not p.alive]
                if dead:
                    log.warning("dead pipelines: %s", dead)
        except KeyboardInterrupt:
            log.info("shutting down")
        finally:
            self.stop()
