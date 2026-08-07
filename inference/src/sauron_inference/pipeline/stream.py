from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable

from ..capture.base import FrameSource
from ..detection.base import Detector
from ..metrics import StreamMetrics
from ..rules.engine import RulesEngine
from ..rules.events import Event
from ..tracking.bytetrack import BYTETracker, STrack
from ..types import Frame, TrackedObject
from .clip import ClipBuffer

log = logging.getLogger(__name__)

TracksCallback = Callable[[str, Frame, list[TrackedObject]], None]
EventCallback = Callable[[Event], None]


def to_tracked_object(track: STrack, frame: Frame) -> TrackedObject:
    x1, y1, x2, y2 = STrack.tlwh_to_xyxy(track.tlwh)
    return TrackedObject(
        object_id=track.track_id,
        camera_id=frame.camera_id,
        class_name=track.class_name,
        class_id=track.class_id,
        bbox=(float(x1), float(y1), float(x2), float(y2)),
        score=track.score,
        centroid=track.centroid,
        velocity=track.velocity,
        track_history=list(track.history),
        frame_seq=frame.seq,
        timestamp=frame.timestamp,
    )


class StreamPipeline:
    """Capture thread -> bounded queue -> detect+track loop for one camera.

    The capture thread owns frame reading (and reconnection). When the queue
    is full the oldest frame is dropped, so inference always works on the
    freshest frame available.
    """

    def __init__(
        self,
        source: FrameSource,
        detector: Detector,
        tracker: BYTETracker,
        on_tracks: TracksCallback | None = None,
        rules_engine: RulesEngine | None = None,
        on_event: EventCallback | None = None,
        clip_buffer: ClipBuffer | None = None,
        queue_size: int = 2,
        metrics: StreamMetrics | None = None,
    ) -> None:
        self.source = source
        self.detector = detector
        self.tracker = tracker
        self.on_tracks = on_tracks
        self.rules_engine = rules_engine
        self.on_event = on_event
        self.clip_buffer = clip_buffer
        self._metrics = metrics
        self._queue: queue.Queue[Frame] = queue.Queue(maxsize=max(queue_size, 1))
        self._stop = threading.Event()
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name=f"cap-{source.camera_id}", daemon=True
        )
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name=f"proc-{source.camera_id}", daemon=True
        )
        self.frames_captured = 0
        self.frames_processed = 0
        self.frames_dropped = 0

    def _capture_loop(self) -> None:
        try:
            for frame in self.source.frames():
                if self._stop.is_set():
                    break
                self.frames_captured += 1
                try:
                    self._queue.put_nowait(frame)
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                        self.frames_dropped += 1
                    except queue.Empty:
                        pass
                    self._queue.put_nowait(frame)
        except Exception:
            log.exception("[%s] capture loop crashed", self.source.camera_id)
        finally:
            self._stop.set()

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                detections = self.detector.detect(frame.image)
                tracks = self.tracker.update(detections)
                tracked = [to_tracked_object(t, frame) for t in tracks]
                self.frames_processed += 1
                if self._metrics is not None:
                    self._metrics.record_processed(frame.camera_id, frame, tracked)
                if self.clip_buffer is not None:
                    self.clip_buffer.add(frame)
                if self.rules_engine is not None:
                    events = self.rules_engine.process(frame, tracked)
                    if events and self.clip_buffer is not None:
                        clip = self.clip_buffer.render_mp4()
                        for event in events:
                            event.clip = clip
                    for event in events:
                        log.info(
                            "[%s] %s %s", frame.camera_id, event.priority, event.event_type
                        )
                        if self._metrics is not None:
                            self._metrics.record_event(frame.camera_id)
                        if self.on_event is not None:
                            self.on_event(event)
                if self.on_tracks is not None:
                    self.on_tracks(frame.camera_id, frame, tracked)
            except Exception:
                log.exception("[%s] processing error at frame %d", frame.camera_id, frame.seq)

    def start(self) -> None:
        self._capture_thread.start()
        self._worker_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self.source.stop()
        self._capture_thread.join(timeout=timeout)
        self._worker_thread.join(timeout=timeout)

    @property
    def alive(self) -> bool:
        return self._capture_thread.is_alive() and self._worker_thread.is_alive()


class NullCallback:
    """Default callback: logs a compact summary every ~5s."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def __call__(self, camera_id: str, frame: Frame, tracks: list[TrackedObject]) -> None:
        now = time.monotonic()
        if now - self._last.get(camera_id, 0) < 5.0:
            return
        self._last[camera_id] = now
        log.info(
            "[%s] frame=%d tracks=%d ids=%s",
            camera_id,
            frame.seq,
            len(tracks),
            [t.object_id for t in tracks][:10],
        )
