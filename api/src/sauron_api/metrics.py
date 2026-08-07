from __future__ import annotations

import threading
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import PlainTextResponse


class ApiMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, int], int] = {}
        self._latency_sum: dict[tuple[str, str], float] = {}
        self._latency_count: dict[tuple[str, str], int] = {}
        self.events_ingested = 0
        self.ws_broadcasts = 0
        self.started_at = time.time()

    def record_request(self, method: str, path: str, status: int, seconds: float) -> None:
        with self._lock:
            key = (method, path, status)
            self._requests[key] = self._requests.get(key, 0) + 1
            route = (method, path)
            self._latency_sum[route] = self._latency_sum.get(route, 0.0) + seconds
            self._latency_count[route] = self._latency_count.get(route, 0) + 1

    def render(self) -> str:
        lines = [
            "# HELP sauron_api_requests_total HTTP requests by route/status",
            "# TYPE sauron_api_requests_total counter",
        ]
        with self._lock:
            for (method, path, status), count in sorted(self._requests.items()):
                lines.append(
                    f'sauron_api_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}'
                )
            lines += [
                "# HELP sauron_api_request_latency_seconds_sum Total latency by route",
                "# TYPE sauron_api_request_latency_seconds_sum counter",
            ]
            for (method, path), total in sorted(self._latency_sum.items()):
                lines.append(
                    f'sauron_api_request_latency_seconds_sum{{method="{method}",path="{path}"}} {total:.4f}'
                )
            lines += [
                "# HELP sauron_api_events_ingested_total Events persisted from pipeline",
                "# TYPE sauron_api_events_ingested_total counter",
                f"sauron_api_events_ingested_total {self.events_ingested}",
                "# HELP sauron_api_ws_broadcasts_total Alerts pushed to WS clients",
                "# TYPE sauron_api_ws_broadcasts_total counter",
                f"sauron_api_ws_broadcasts_total {self.ws_broadcasts}",
                "# HELP sauron_api_uptime_seconds Process uptime",
                "# TYPE sauron_api_uptime_seconds gauge",
                f"sauron_api_uptime_seconds {time.time() - self.started_at:.0f}",
            ]
        return "\n".join(lines) + "\n"


metrics = ApiMetrics()

_ROUTE_LABELS = {
    "/api/v1/events": "events",
    "/api/v1/cameras": "cameras",
    "/api/v1/kpis": "kpis",
    "/api/v1/branding": "branding",
    "/healthz": "healthz",
}


def _route_label(path: str) -> str:
    for prefix, label in _ROUTE_LABELS.items():
        if path.startswith(prefix):
            return label
    if path.startswith("/api/v1/reports"):
        return "reports"
    return "other"


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path == "/metrics":
            return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")
        t0 = time.monotonic()
        response = await call_next(request)
        metrics.record_request(
            request.method, _route_label(request.url.path), response.status_code,
            time.monotonic() - t0,
        )
        return response
