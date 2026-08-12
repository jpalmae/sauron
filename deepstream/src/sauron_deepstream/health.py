from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .metrics import Metrics


class HealthServer:
    def __init__(self, port: int, metrics: Metrics) -> None:
        self._port = port
        self._metrics = metrics
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        metrics = self._metrics

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/healthz":
                    status = HTTPStatus.OK if metrics.ready else HTTPStatus.SERVICE_UNAVAILABLE
                    body = json.dumps({"status": "ok" if metrics.ready else "starting"}).encode()
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                elif self.path == "/metrics":
                    body = metrics.prometheus().encode()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/plain; version=0.0.4")
                else:
                    body = b"not found"
                    self.send_response(HTTPStatus.NOT_FOUND)
                    self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    # TensorRT can briefly monopolize the process while an
                    # engine is compiled. A timed-out health client may close
                    # its socket before the response is written.
                    return

            def log_message(self, _format: str, *_args) -> None:
                return

        self._server = ThreadingHTTPServer(("0.0.0.0", self._port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
