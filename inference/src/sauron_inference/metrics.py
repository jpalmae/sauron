from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .types import Frame, TrackedObject

PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class StreamMetrics:
    """Per-camera counters, rendered in Prometheus text format."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._captured: dict[str, int] = {}
        self._processed: dict[str, int] = {}
        self._dropped: dict[str, int] = {}
        self._tracks: dict[str, int] = {}
        self._events: dict[str, int] = {}
        self._latency_ms: dict[str, float] = {}
        self._last_frame_ts: dict[str, float] = {}

    def record_processed(self, camera_id: str, frame: Frame, tracks: list[TrackedObject]) -> None:
        with self._lock:
            self._processed[camera_id] = self._processed.get(camera_id, 0) + 1
            self._tracks[camera_id] = len(tracks)
            self._latency_ms[camera_id] = (time.time() - frame.timestamp) * 1000
            self._last_frame_ts[camera_id] = frame.timestamp

    def record_event(self, camera_id: str) -> None:
        with self._lock:
            self._events[camera_id] = self._events.get(camera_id, 0) + 1

    def sync_counters(self, camera_id: str, captured: int, dropped: int) -> None:
        with self._lock:
            self._captured[camera_id] = captured
            self._dropped[camera_id] = dropped

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name, series, help_text in [
                ("sauron_frames_captured_total", self._captured, "Frames read from source"),
                ("sauron_frames_processed_total", self._processed, "Frames through inference+tracking"),
                ("sauron_frames_dropped_total", self._dropped, "Frames dropped by bounded queue"),
                ("sauron_tracks_active", self._tracks, "Active tracks in last processed frame"),
                ("sauron_events_total", self._events, "Rule events emitted"),
            ]:
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} counter" if name.endswith("_total") else f"# TYPE {name} gauge")
                for cam, value in series.items():
                    lines.append(f'{name}{{camera="{cam}"}} {value}')
            lines.append("# HELP sauron_pipeline_latency_ms Last frame end-to-end latency")
            lines.append("# TYPE sauron_pipeline_latency_ms gauge")
            for cam, lat in self._latency_ms.items():
                lines.append(f'sauron_pipeline_latency_ms{{camera="{cam}"}} {lat:.1f}')
            lines.append("# HELP sauron_last_frame_timestamp_seconds Unix ts of last processed frame")
            lines.append("# TYPE sauron_last_frame_timestamp_seconds gauge")
            for cam, ts in self._last_frame_ts.items():
                lines.append(f'sauron_last_frame_timestamp_seconds{{camera="{cam}"}} {ts:.3f}')
        return "\n".join(lines) + "\n"


def make_handler(metrics: StreamMetrics):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/metrics":
                body = metrics.render().encode()
                self.send_response(200)
                self.send_header("Content-Type", PROM_CONTENT_TYPE)
            elif self.path == "/healthz":
                body = b'{"status":"ok"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
            else:
                body = b"not found"
                self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:
            pass

    return Handler


def start_metrics_server(metrics: StreamMetrics, port: int = 9100) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(metrics))
    threading.Thread(target=server.serve_forever, name="metrics-http", daemon=True).start()
    return server
