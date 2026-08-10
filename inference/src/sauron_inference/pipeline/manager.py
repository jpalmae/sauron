from __future__ import annotations

import hashlib
import json
import logging
import os
import time

from ..bridge.http_publisher import HTTPEventPublisher
from ..bridge.redis_publisher import RedisEventPublisher
from ..capture.base import FrameSource
from ..capture.rtsp import RTSPSource
from ..capture.synthetic import FileSource, SyntheticSource
from ..config import DefaultsConfig, PipelineConfig, StreamConfig
from ..detection.base import Detector
from ..detection.mock import MockDetector
from ..detection.multi import MultiDetector
from ..detection.onnx_dnn import OnnxDnnDetector
from ..detection.openai_compat import OpenAICompatDetector
from ..detection.pose import OnnxPoseDetector
from ..detection.tensorrt_yolo import TensorRTYolo
from ..metrics import StreamMetrics
from ..models import engine_path, onnx_path
from ..ptz import PtzController
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
    if det_cfg.backend == "pose":
        return OnnxPoseDetector(
            onnx_path=stream.resolved_pose_onnx(cfg.defaults),
            input_size=cfg.defaults.input_size,
            conf_threshold=conf,
            nms_threshold=cfg.defaults.nms_threshold,
            classes=cfg.defaults.classes,
        )
    if det_cfg.backend == "pose_objects":
        return MultiDetector(
            pose_path=stream.resolved_pose_onnx(cfg.defaults),
            objects_path=stream.resolved_objects_onnx(cfg.defaults),
            input_size=cfg.defaults.input_size,
            conf_threshold=conf,
            nms_threshold=cfg.defaults.nms_threshold,
            pose_classes={0: "person"},
            objects_classes=cfg.defaults.classes,
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
    """Builds and supervises one StreamPipeline per configured stream.

    Two camera sources are supported:
      * static YAML streams (default), and
      * dynamic cameras pulled from the Sauron API via ``camera_source`` —
        enables 100% GUI-driven camera management (add/edit/remove in the
        dashboard; the engine reconciles within the poll interval).

    Camera health: emits CAMERA_OFFLINE when a stream stops producing frames
    for ``offline_seconds``, CAMERA_ONLINE when it recovers.
    """

    def __init__(
        self,
        cfg: PipelineConfig,
        on_tracks: TracksCallback | None = None,
        on_event: EventCallback | None = None,
        detector_factory=build_detector,
        source_factory=build_source,
        camera_source=None,
        offline_seconds: float = 60.0,
    ) -> None:
        self.cfg = cfg
        self._user_on_tracks = on_tracks
        self._detections_publisher = self._build_detections_publisher()
        self.on_tracks = self._on_tracks
        self._user_on_event = on_event
        self.on_event = self._build_event_sink()
        self._detector_factory = detector_factory
        self._source_factory = source_factory
        self.pipelines: list[StreamPipeline] = []
        self.metrics = StreamMetrics()
        self.camera_source = camera_source
        self.offline_seconds = offline_seconds
        self._audio_taps: list = []
        self._stream_hashes: dict[str, str] = {}
        self._last_frame: dict[str, float] = {}
        self._processed_seen: dict[str, int] = {}
        self._offline: set[str] = set()
        self._last_sync = -1.0
        self._defaults_hash: str = ""

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

    def _build_detections_publisher(self):
        redis_url = os.environ.get("SAURON_REDIS_URL") or self.cfg.app.redis_url
        if not redis_url:
            return None
        try:
            from ..bridge.detections_publisher import RedisDetectionsPublisher
            log.info("publishing live detections to redis")
            return RedisDetectionsPublisher(redis_url)
        except Exception:
            log.exception("detections publisher init failed")
            return None

    def _on_tracks(self, camera_id, frame, tracks):
        if self._user_on_tracks is not None:
            try:
                self._user_on_tracks(camera_id, frame, tracks)
            except Exception:
                log.exception("on_tracks callback failed")
        if self._detections_publisher is not None:
            self._detections_publisher(camera_id, frame, tracks)

    @staticmethod
    def _hash(stream: StreamConfig) -> str:
        payload = {
            "type": stream.type,
            "source": stream.source,
            "target_fps": stream.target_fps,
            "detector": stream.detector.model_dump(mode="json") if stream.detector else None,
            "roi": stream.roi.model_dump(mode="json") if stream.roi else None,
        }
        return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _build_one(self, stream: StreamConfig, index: int) -> StreamPipeline:
        device_id = self.cfg.device_for(index, stream)
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
        log.info("stream %s assigned to GPU %d", stream.id, device_id)
        pipeline = StreamPipeline(
            source=source,
            detector=detector,
            tracker=tracker,
            on_tracks=self.on_tracks,
            rules_engine=engine,
            on_event=self.on_event,
            clip_buffer=clip_buffer,
            queue_size=self.cfg.defaults.capture.queue_size,
            metrics=self.metrics,
            ptz=PtzController(stream.ptz) if stream.ptz else None,
        )
        if stream.audio is not None and stream.audio.enabled:
            from ..audio import AudioTap

            tap = AudioTap(stream.id, stream.source, stream.audio, self.on_event)
            pipeline.audio_tap = tap
            self._audio_taps.append(tap)
        return pipeline

    def _start_one(self, stream: StreamConfig) -> None:
        try:
            pipeline = self._build_one(stream, len(self.pipelines))
            pipeline.start()
            self.pipelines.append(pipeline)
            self._stream_hashes[stream.id] = self._hash(stream)
            log.info("stream %s started (source=%s)", stream.id, stream.source)
        except Exception:
            log.exception("error starting stream %s", stream.id)

    def build(self) -> None:
        for i, stream in enumerate(self.cfg.streams):
            pipeline = self._build_one(stream, i)
            self.pipelines.append(pipeline)
            self._stream_hashes[stream.id] = self._hash(stream)

    def reconcile(self, desired: list[StreamConfig]) -> None:
        """Add/remove/restart streams so the running set matches ``desired``."""
        desired_ids = {s.id for s in desired}
        desired_hashes = {s.id: self._hash(s) for s in desired}

        to_stop = [
            p
            for p in self.pipelines
            if p.source.camera_id not in desired_ids
            or desired_hashes.get(p.source.camera_id)
            != self._stream_hashes.get(p.source.camera_id)
        ]
        for p in to_stop:
            try:
                p.stop()
            except Exception:
                log.exception("error stopping stream %s", p.source.camera_id)
            log.info("stream %s stopped", p.source.camera_id)
        if to_stop:
            stopped = {p.source.camera_id for p in to_stop}
            self.pipelines = [p for p in self.pipelines if p.source.camera_id not in stopped]
            for cid in stopped:
                self._stream_hashes.pop(cid, None)

        running_ids = {p.source.camera_id for p in self.pipelines}
        for s in desired:
            if s.id not in running_ids:
                self._start_one(s)

    def start(self) -> None:
        # In API (GUI-driven) mode the camera list comes from reconcile().
        if not self.camera_source and not self.pipelines:
            self.build()
        for p in self.pipelines:
            p.start()
            if p.audio_tap is not None:
                p.audio_tap.start()
        log.info("started %d stream pipelines", len(self.pipelines))

    def stop(self) -> None:
        for tap in self._audio_taps:
            tap.stop()
        for p in self.pipelines:
            p.stop()
        log.info("all pipelines stopped")

    def _stop_all(self) -> None:
        for p in self.pipelines:
            try:
                p.stop()
            except Exception:
                log.exception("error stopping stream %s", p.source.camera_id)
        self.pipelines = []
        self._stream_hashes.clear()

    def _sync_cameras(self) -> None:
        self._last_sync = time.monotonic()
        try:
            ec = self.camera_source.fetch_engine_config()
            if ec is not None:
                new_defaults, new_fps = ec
                dh = hashlib.sha1(json.dumps(new_defaults, sort_keys=True).encode()).hexdigest()
                if dh != self._defaults_hash:
                    try:
                        self.cfg.defaults = DefaultsConfig.model_validate(new_defaults)
                        self._defaults_hash = dh
                        self._stop_all()
                        log.info("engine defaults reloaded from API")
                    except Exception:
                        log.exception("invalid engine defaults; keeping current")
                if new_fps and new_fps != self.camera_source.target_fps:
                    self.camera_source.target_fps = new_fps
                    self._stop_all()
                    log.info("target_fps reloaded -> %s", new_fps)
            desired = self.camera_source.fetch_streams()
            log.debug("camera source returned %d streams", len(desired))
            self.reconcile(desired)
        except Exception:
            log.exception("camera sync failed")

    def _check_camera_health(self) -> None:
        """Emit CAMERA_OFFLINE / CAMERA_ONLINE based on per-stream liveness."""
        from ..rules.events import Event, EventType, Priority

        now = time.monotonic()
        for p in self.pipelines:
            cid = p.source.camera_id
            if p.frames_processed > self._processed_seen.get(cid, 0):
                self._processed_seen[cid] = p.frames_processed
                self._last_frame[cid] = now
                if cid in self._offline:
                    self._offline.discard(cid)
                    self._emit_health(
                        Event(
                            event_type=EventType.CAMERA_ONLINE,
                            camera_id=cid,
                            timestamp=time.time(),
                            confidence=1.0,
                            priority=Priority.INFO,
                            rule_id="camera-health",
                            metadata={"recovered": True},
                        )
                    )
                continue
            last = self._last_frame.get(cid)
            idle = now - last if last is not None else 0.0
            if last is not None and idle > self.offline_seconds and cid not in self._offline:
                self._offline.add(cid)
                self._emit_health(
                    Event(
                        event_type=EventType.CAMERA_OFFLINE,
                        camera_id=cid,
                        timestamp=time.time(),
                        confidence=1.0,
                        priority=Priority.WARNING,
                        rule_id="camera-health",
                        metadata={"idle_seconds": round(idle)},
                    )
                )

    def _emit_health(self, event) -> None:
        log.warning("[%s] %s", event.camera_id, event.event_type)
        self.metrics.record_event(event.camera_id)
        if self.on_event is not None:
            self.on_event(event)

    def run_forever(self, elector=None) -> None:
        if elector is None:
            self.start()
        try:
            while True:
                time.sleep(5)
                if elector is not None:
                    if elector.try_acquire():
                        if not self.pipelines:
                            log.info("leadership acquired; starting pipelines")
                            self.start()
                    elif self.pipelines:
                        log.warning("standby mode; stopping pipelines")
                        self.stop()
                        self.pipelines = []
                elif self.camera_source is not None:
                    interval = getattr(self.camera_source, "poll_interval", 20.0)
                    if time.monotonic() - self._last_sync >= interval:
                        self._sync_cameras()
                for p in self.pipelines:
                    self.metrics.sync_counters(
                        p.source.camera_id, p.frames_captured, p.frames_dropped
                    )
                self._check_camera_health()
                dead = [p.source.camera_id for p in self.pipelines if not p.alive]
                if dead:
                    log.warning("dead pipelines: %s", dead)
        except KeyboardInterrupt:
            log.info("shutting down")
        finally:
            self.stop()
            if elector is not None:
                elector.release()
            if self.camera_source is not None:
                try:
                    self.camera_source.close()
                except Exception:
                    log.debug("camera source close failed", exc_info=True)
