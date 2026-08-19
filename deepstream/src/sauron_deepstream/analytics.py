from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from .bridge import RedisStreamBridge
from .domain import Frame, TrackedObject
from .evidence import EvidenceManager
from .metrics import Metrics
from .registry import Camera, CameraRegistry
from .rules import RulesEngine


@dataclass(slots=True)
class _TrackState:
    centroid: tuple[float, float]
    timestamp: float
    history: deque[tuple[float, float]]
    last_frame: int


@dataclass(frozen=True, slots=True)
class Detection:
    """Primitive copy of one DeepStream object safe beyond metadata iteration."""

    object_id: int
    class_id: int
    confidence: float
    tracker_confidence: float
    bbox: tuple[float, float, float, float]
    vehicle_type: str | None


class TrackAssembler:
    """Convert NvDCF metadata to the rule engine's stable track contract."""

    def __init__(self, labels: list[str], fps: int, history_size: int = 60) -> None:
        self._labels = labels
        self._fps = fps
        self._history_size = history_size
        self._state: dict[tuple[str, int], _TrackState] = {}

    def assemble(
        self,
        camera_id: str,
        frame_number: int,
        timestamp: float,
        detections: list[Detection],
    ) -> list[TrackedObject]:
        tracks: list[TrackedObject] = []
        active: set[tuple[str, int]] = set()
        for detection in detections:
            object_id = detection.object_id
            # UINT64_MAX means the object was not assigned a tracker ID.
            if object_id < 0 or object_id == 0xFFFFFFFFFFFFFFFF:
                continue
            x1, y1, x2, y2 = detection.bbox
            centroid = ((x1 + x2) / 2, (y1 + y2) / 2)
            key = (camera_id, object_id)
            previous = self._state.get(key)
            if previous is None:
                history: deque[tuple[float, float]] = deque(maxlen=self._history_size)
                velocity = (0.0, 0.0)
            else:
                history = previous.history
                dt = max(timestamp - previous.timestamp, 1e-3)
                # Existing rules express velocity in px/frame and multiply by
                # configured FPS. Normalize elapsed-time motion accordingly.
                velocity = (
                    (centroid[0] - previous.centroid[0]) / dt / self._fps,
                    (centroid[1] - previous.centroid[1]) / dt / self._fps,
                )
            history.append(centroid)
            self._state[key] = _TrackState(centroid, timestamp, history, frame_number)
            active.add(key)
            class_id = detection.class_id
            label = self._labels[class_id] if 0 <= class_id < len(self._labels) else str(class_id)
            score = (
                detection.tracker_confidence
                if detection.tracker_confidence > 0
                else detection.confidence
            )
            tracks.append(
                TrackedObject(
                    object_id=object_id,
                    camera_id=camera_id,
                    class_name=label,
                    class_id=class_id,
                    bbox=(x1, y1, x2, y2),
                    score=score,
                    centroid=centroid,
                    velocity=velocity,
                    track_history=list(history),
                    frame_seq=frame_number,
                    timestamp=timestamp,
                )
            )
        stale = [
            key
            for key, state in self._state.items()
            if key[0] == camera_id
            and key not in active
            and frame_number - state.last_frame > self._fps * 5
        ]
        for key in stale:
            self._state.pop(key, None)
        return tracks


class MetadataProcessor:
    """Small, testable metadata path called by the Service Maker probe."""

    def __init__(
        self,
        registry: CameraRegistry,
        bridge: RedisStreamBridge,
        metrics: Metrics,
        labels: list[str],
        fps: int,
        evidence: EvidenceManager | None = None,
    ) -> None:
        self._registry = registry
        self._bridge = bridge
        self._metrics = metrics
        self._fps = fps
        self._evidence = evidence
        self._tracks = TrackAssembler(labels, fps)
        self._engines: dict[str, tuple[str, RulesEngine]] = {}
        self._vehicle_types: dict[tuple[str, int], str] = {}
        self._vehicle_type_seen: dict[tuple[str, int], float] = {}

    def process_batch(self, batch_meta: Any) -> None:
        for frame_meta in batch_meta.frame_items:
            source_id = int(getattr(frame_meta, "source_id", frame_meta.pad_index))
            camera = self._registry.camera_for_source(source_id)
            if camera is None:
                continue
            timestamp = _frame_timestamp(frame_meta)
            frame_number = int(frame_meta.frame_number)
            width = int(getattr(frame_meta, "source_frame_width", 0) or 1280)
            height = int(getattr(frame_meta, "source_frame_height", 0) or 720)
            # Service Maker metadata wrappers are owned by their iterators. Do
            # not keep ObjectMetadata instances after advancing/destroying the
            # iterator; copy all required primitive values in one pass.
            detections = _extract_detections(frame_meta)
            tracks = self._tracks.assemble(
                camera.stream_id,
                frame_number,
                timestamp,
                detections,
            )
            for detection in detections:
                key = (camera.stream_id, detection.object_id)
                self._vehicle_type_seen[key] = timestamp
                if detection.vehicle_type:
                    self._vehicle_types[key] = detection.vehicle_type
            stale_vehicle_types = [
                key
                for key, last_seen in self._vehicle_type_seen.items()
                if key[0] == camera.stream_id and timestamp - last_seen > 60
            ]
            for key in stale_vehicle_types:
                self._vehicle_type_seen.pop(key, None)
                self._vehicle_types.pop(key, None)
            self._metrics.record_frame(camera.stream_id, len(tracks), timestamp)
            self._bridge.submit_detections(
                camera.stream_id,
                {
                    "ts": timestamp,
                    "frame_seq": frame_number,
                    "width": width,
                    "height": height,
                    "objects": [
                        {
                            "id": track.object_id,
                            "class": track.class_name,
                            "confidence": round(track.score, 4),
                            "vehicle_type": self._vehicle_types.get(
                                (camera.stream_id, track.object_id)
                            ),
                            "box": [
                                track.bbox[0] / width,
                                track.bbox[1] / height,
                                track.bbox[2] / width,
                                track.bbox[3] / height,
                            ],
                        }
                        for track in tracks
                    ],
                },
            )
            engine = self._engine(camera)
            if engine is None:
                continue
            # Rules use geometry only in DeepStream mode. Frame pixels never
            # leave NVMM, avoiding an expensive GPU-to-CPU copy per stream.
            frame = Frame(
                camera_id=camera.stream_id,
                seq=frame_number,
                timestamp=timestamp,
            )
            for event in engine.process(frame, tracks):
                if event.object_id is not None:
                    vehicle_type = self._vehicle_types.get((camera.stream_id, event.object_id))
                    if vehicle_type:
                        event.metadata["vehicle_type"] = vehicle_type
                self._metrics.record_event(camera.stream_id)
                if self._evidence is not None:
                    queued = self._evidence.submit(event, camera, tracks, width, height)
                    event.metadata["evidence_status"] = "pending" if queued else "unavailable"
                self._bridge.submit_event(event)

    def _engine(self, camera: Camera) -> RulesEngine | None:
        if camera.roi is None:
            return None
        fingerprint = camera.roi.model_dump_json()
        current = self._engines.get(camera.stream_id)
        if current is None or current[0] != fingerprint:
            roi = camera.roi.model_copy(deep=True)
            # ALPR requires pixel crops and is intentionally outside this
            # zero-copy traffic pipeline. It can be added later as a gated
            # secondary branch without slowing every camera.
            roi.alpr = None
            current = (
                fingerprint,
                RulesEngine(
                    camera.stream_id,
                    roi,
                    fps=self._fps,
                ),
            )
            self._engines[camera.stream_id] = current
        return current[1]


def _frame_timestamp(frame_meta: Any) -> float:
    value = int(getattr(frame_meta, "ntp_timestamp", 0) or 0)
    if value >= 1_000_000_000_000_000:
        return value / 1_000_000_000
    return time.time()


def _extract_detections(frame_meta: Any) -> list[Detection]:
    detections: list[Detection] = []
    for obj in frame_meta.object_items:
        object_id = int(obj.object_id)
        class_id = int(obj.class_id)
        confidence = float(getattr(obj, "confidence", 0.0))
        tracker_confidence = float(getattr(obj, "tracker_confidence", 0.0))
        rect = obj.rect_params
        left = float(rect.left)
        top = float(rect.top)
        detections.append(
            Detection(
                object_id=object_id,
                class_id=class_id,
                confidence=confidence,
                tracker_confidence=tracker_confidence,
                bbox=(left, top, left + float(rect.width), top + float(rect.height)),
                vehicle_type=_classifier_label(obj, component_id=2),
            )
        )
    return detections


def _classifier_label(obj: Any, component_id: int) -> str | None:
    """Read an SGIE label from native Service Maker object metadata."""
    for classifier in getattr(obj, "classifier_items", ()):
        if int(classifier.unique_component_id) != component_id:
            continue
        for index in range(int(classifier.n_labels)):
            label = classifier.get_n_label(index)
            if isinstance(label, bytes):
                label = label.decode(errors="replace")
            label = str(label).strip()
            if label:
                return label
    return None


def make_metadata_operator(processor: MetadataProcessor):
    """Import Service Maker only inside its DeepStream runtime."""
    from pyservicemaker import BatchMetadataOperator

    class SauronMetadataOperator(BatchMetadataOperator):
        def __init__(self) -> None:
            super().__init__()

        def handle_metadata(self, batch_meta) -> None:
            processor.process_batch(batch_meta)

    return SauronMetadataOperator()
