from __future__ import annotations

import threading
import time
from collections import Counter


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

    def record_frame(self, camera_id: str, objects: int, timestamp: float) -> None:
        with self._lock:
            self.frames[camera_id] += 1
            self.objects[camera_id] += objects
            self.last_frame[camera_id] = timestamp

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
            lines.append("# TYPE sauron_deepstream_metadata_dropped_total counter")
            lines.extend(
                f'sauron_deepstream_metadata_dropped_total{{kind="{kind}"}} {value}'
                for kind, value in sorted(self.dropped_metadata.items())
            )
        return "\n".join(lines) + "\n"
