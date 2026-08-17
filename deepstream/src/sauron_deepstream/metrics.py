from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Iterable
from typing import Any


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.ready = False
        self.started_at = time.time()
        self.frames: Counter[str] = Counter()
        self.objects: Counter[str] = Counter()
        self.events: Counter[str] = Counter()
        self.dropped_metadata: Counter[str] = Counter()
        self.last_frame: dict[str, float] = {}
        self.recoveries: Counter[str] = Counter()
        self._active_since: dict[str, float] = {}
        self._last_frame_seen: dict[str, float] = {}
        self._recovery_started: dict[str, float] = {}
        self._consecutive_recoveries: Counter[str] = Counter()

    def set_active_cameras(
        self, camera_ids: Iterable[str], now_monotonic: float | None = None
    ) -> None:
        """Track the cameras that are expected to be producing frames."""
        now = time.monotonic() if now_monotonic is None else now_monotonic
        active = set(camera_ids)
        with self._lock:
            for camera_id in active:
                self._active_since.setdefault(camera_id, now)
            for camera_id in set(self._active_since) - active:
                self._active_since.pop(camera_id, None)
                self._last_frame_seen.pop(camera_id, None)
                self._recovery_started.pop(camera_id, None)
                self._consecutive_recoveries.pop(camera_id, None)

    def record_frame(
        self,
        camera_id: str,
        objects: int,
        timestamp: float,
        now_monotonic: float | None = None,
    ) -> None:
        now = time.monotonic() if now_monotonic is None else now_monotonic
        with self._lock:
            self.frames[camera_id] += 1
            self.objects[camera_id] += objects
            self.last_frame[camera_id] = timestamp
            self._active_since.setdefault(camera_id, now)
            self._last_frame_seen[camera_id] = now
            self._recovery_started.pop(camera_id, None)
            self._consecutive_recoveries[camera_id] = 0

    def recovery_candidates(
        self,
        stale_after: float,
        cooldown: float,
        max_attempts: int,
        now_monotonic: float | None = None,
    ) -> list[str]:
        """Return stalled cameras that are eligible for a source-level restart."""
        now = time.monotonic() if now_monotonic is None else now_monotonic
        with self._lock:
            candidates: list[str] = []
            for camera_id, active_since in self._active_since.items():
                if self._consecutive_recoveries[camera_id] >= max_attempts:
                    continue
                recovery_started = self._recovery_started.get(camera_id)
                if recovery_started is not None:
                    if now - recovery_started >= max(stale_after, cooldown):
                        candidates.append(camera_id)
                    continue
                last_seen = self._last_frame_seen.get(camera_id)
                baseline = last_seen if last_seen is not None else active_since
                if now - baseline >= stale_after:
                    candidates.append(camera_id)
            return candidates

    def begin_recovery(self, camera_id: str, now_monotonic: float | None = None) -> int:
        now = time.monotonic() if now_monotonic is None else now_monotonic
        with self._lock:
            self.recoveries[camera_id] += 1
            self._consecutive_recoveries[camera_id] += 1
            self._recovery_started[camera_id] = now
            return self._consecutive_recoveries[camera_id]

    def health_snapshot(
        self,
        stale_after: float,
        max_recovery_attempts: int,
        now_monotonic: float | None = None,
    ) -> dict[str, Any]:
        """Return process and per-camera liveness derived from actual frames."""
        now = time.monotonic() if now_monotonic is None else now_monotonic
        with self._lock:
            cameras: dict[str, dict[str, Any]] = {}
            for camera_id, active_since in sorted(self._active_since.items()):
                last_seen = self._last_frame_seen.get(camera_id)
                recovery_started = self._recovery_started.get(camera_id)
                attempts = self._consecutive_recoveries[camera_id]
                if recovery_started is not None:
                    age = now - recovery_started
                    state = "recovering"
                elif last_seen is None:
                    age = now - active_since
                    state = "starting" if age < stale_after else "stale"
                else:
                    age = now - last_seen
                    state = "live" if age < stale_after else "stale"
                exhausted = (
                    attempts >= max_recovery_attempts
                    and state != "live"
                    and age >= stale_after
                )
                if exhausted:
                    state = "failed"
                cameras[camera_id] = {
                    "state": state,
                    "last_frame_age_seconds": round(age, 3),
                    "last_frame_timestamp": self.last_frame.get(camera_id),
                    "frames": self.frames[camera_id],
                    "objects": self.objects[camera_id],
                    "recovery_attempts": attempts,
                    "recoveries_total": self.recoveries[camera_id],
                }

            if not self.ready:
                status = "starting"
                healthy = False
            elif any(camera["state"] == "failed" for camera in cameras.values()):
                status = "unhealthy"
                healthy = False
            elif any(camera["state"] != "live" for camera in cameras.values()):
                status = "degraded"
                healthy = True
            else:
                status = "ok"
                healthy = True
            return {
                "status": status,
                "ready": self.ready,
                "healthy": healthy,
                "active_cameras": len(cameras),
                "live_cameras": sum(camera["state"] == "live" for camera in cameras.values()),
                "cameras": cameras,
            }

    def failed_camera_ids(
        self,
        stale_after: float,
        max_recovery_attempts: int,
        now_monotonic: float | None = None,
    ) -> list[str]:
        snapshot = self.health_snapshot(
            stale_after,
            max_recovery_attempts,
            now_monotonic=now_monotonic,
        )
        return [
            camera_id
            for camera_id, camera in snapshot["cameras"].items()
            if camera["state"] == "failed"
        ]

    def record_event(self, camera_id: str) -> None:
        with self._lock:
            self.events[camera_id] += 1

    def record_drop(self, kind: str) -> None:
        with self._lock:
            self.dropped_metadata[kind] += 1

    def prometheus(self) -> str:
        with self._lock:
            lines = [
                "# TYPE sauron_deepstream_ready gauge",
                f"sauron_deepstream_ready {1 if self.ready else 0}",
                "# TYPE sauron_deepstream_uptime_seconds gauge",
                f"sauron_deepstream_uptime_seconds {time.time() - self.started_at:.3f}",
            ]
            for metric, values in (
                ("frames_processed_total", self.frames),
                ("objects_total", self.objects),
                ("events_total", self.events),
            ):
                lines.append(f"# TYPE sauron_{metric} counter")
                lines.extend(
                    f'sauron_{metric}{{camera="{camera}"}} {value}'
                    for camera, value in sorted(values.items())
                )
            lines.append("# TYPE sauron_deepstream_last_frame_timestamp_seconds gauge")
            lines.extend(
                f'sauron_deepstream_last_frame_timestamp_seconds{{camera="{camera}"}} {value:.3f}'
                for camera, value in sorted(self.last_frame.items())
            )
            lines.append("# TYPE sauron_deepstream_source_recoveries_total counter")
            lines.extend(
                f'sauron_deepstream_source_recoveries_total{{camera="{camera}"}} {value}'
                for camera, value in sorted(self.recoveries.items())
            )
            lines.append("# TYPE sauron_deepstream_metadata_dropped_total counter")
            lines.extend(
                f'sauron_deepstream_metadata_dropped_total{{kind="{kind}"}} {value}'
                for kind, value in sorted(self.dropped_metadata.items())
            )
        return "\n".join(lines) + "\n"
