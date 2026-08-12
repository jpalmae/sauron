from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any

from .domain import Event
from .metrics import Metrics

log = logging.getLogger(__name__)

DETECTIONS_PREFIX = "sauron:detections:"
EVENTS_STREAM = "sauron:events:stream"


@dataclass(frozen=True, slots=True)
class DetectionEnvelope:
    camera_id: str
    payload: dict[str, Any]


class RedisStreamBridge:
    """Non-blocking handoff from the GStreamer thread to Redis.

    Live overlays are deliberately lossy and expire after five seconds. Events
    are appended to a Redis Stream so the API can acknowledge them only after
    persistence, rather than losing them during a restart as Pub/Sub did.
    """

    def __init__(self, redis_url: str, metrics: Metrics) -> None:
        self._redis_url = redis_url
        self._metrics = metrics
        self._detections: queue.Queue[DetectionEnvelope] = queue.Queue(maxsize=256)
        self._events: queue.Queue[Event] = queue.Queue(maxsize=8192)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="redis-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def submit_detections(self, camera_id: str, payload: dict[str, Any]) -> None:
        envelope = DetectionEnvelope(camera_id, payload)
        try:
            self._detections.put_nowait(envelope)
        except queue.Full:
            # Prefer the newest overlay snapshot.
            try:
                self._detections.get_nowait()
            except queue.Empty:
                pass
            try:
                self._detections.put_nowait(envelope)
            except queue.Full:
                pass
            self._metrics.record_drop("detections")

    def submit_event(self, event: Event) -> None:
        try:
            self._events.put_nowait(event)
        except queue.Full:
            self._metrics.record_drop("events")
            log.error("event queue full; dropping %s from %s", event.event_type, event.camera_id)

    def _run(self) -> None:
        import redis

        client = redis.Redis.from_url(self._redis_url, socket_timeout=5, retry_on_timeout=True)
        while not self._stop.is_set():
            worked = False
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                event = None
            if event is not None:
                worked = True
                try:
                    client.xadd(
                        EVENTS_STREAM,
                        {"data": json.dumps(event.to_dict(), separators=(",", ":"))},
                        maxlen=100_000,
                        approximate=True,
                    )
                except Exception:
                    log.exception("failed to append event; retrying")
                    try:
                        self._events.put_nowait(event)
                    except queue.Full:
                        self._metrics.record_drop("events")
                    self._stop.wait(1)
            try:
                detection = self._detections.get_nowait()
            except queue.Empty:
                detection = None
            if detection is not None:
                worked = True
                try:
                    client.set(
                        f"{DETECTIONS_PREFIX}{detection.camera_id}",
                        json.dumps(detection.payload, separators=(",", ":")),
                        ex=5,
                    )
                except Exception:
                    log.exception("failed to publish live detections")
            if not worked:
                self._stop.wait(0.02)
