from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .domain import ROIConfig


@dataclass(frozen=True, slots=True)
class Camera:
    stream_id: str
    name: str
    uri: str
    analytics_profile: str
    roi: ROIConfig | None


class CameraRegistry:
    """Thread-safe mapping between DeepStream source IDs and Sauron cameras."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cameras: dict[str, Camera] = {}
        self._source_to_stream: dict[int, str] = {}

    def set_camera(self, camera: Camera) -> None:
        with self._lock:
            self._cameras[camera.stream_id] = camera

    def remove_camera(self, stream_id: str) -> None:
        with self._lock:
            self._cameras.pop(stream_id, None)
            stale = [source_id for source_id, sid in self._source_to_stream.items() if sid == stream_id]
            for source_id in stale:
                self._source_to_stream.pop(source_id, None)

    def bind_source(self, source_id: int, stream_id: str) -> None:
        with self._lock:
            if stream_id in self._cameras:
                self._source_to_stream[source_id] = stream_id

    def unbind_source(self, source_id: int) -> None:
        with self._lock:
            self._source_to_stream.pop(source_id, None)

    def is_bound(self, stream_id: str) -> bool:
        with self._lock:
            return stream_id in self._source_to_stream.values()

    def camera_for_source(self, source_id: int) -> Camera | None:
        with self._lock:
            stream_id = self._source_to_stream.get(source_id)
            return self._cameras.get(stream_id) if stream_id else None

    def camera(self, stream_id: str) -> Camera | None:
        with self._lock:
            return self._cameras.get(stream_id)

    def snapshot(self) -> dict[str, Camera]:
        with self._lock:
            return dict(self._cameras)


def camera_from_api(payload: dict[str, Any], resolved_uri: str | None = None) -> Camera:
    stream_id = str(payload["stream_id"])
    roi = None
    if payload.get("roi_config"):
        roi = ROIConfig.model_validate(payload["roi_config"])
    return Camera(
        stream_id=stream_id,
        name=str(payload.get("name") or stream_id),
        uri=resolved_uri or str(payload.get("rtsp_url") or ""),
        analytics_profile=str(payload.get("analytics_profile") or "traffic"),
        roi=roi,
    )
