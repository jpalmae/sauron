from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from .registry import Camera, CameraRegistry, camera_from_api
from .sources import resolve_source

log = logging.getLogger(__name__)


class SourceController:
    """Reconcile API cameras with nvmultiurisrcbin's built-in REST API."""

    def __init__(
        self,
        api_url: str,
        ingest_token: str,
        rest_port: int,
        poll_seconds: float,
        max_streams: int,
        registry: CameraRegistry,
    ) -> None:
        self._api_url = api_url
        self._headers = {"Authorization": f"Bearer {ingest_token}"} if ingest_token else {}
        self._rest_url = f"http://127.0.0.1:{rest_port}"
        self._poll_seconds = poll_seconds
        self._max_streams = max_streams
        self._registry = registry
        self._active: dict[str, Camera] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="source-controller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        with httpx.Client(timeout=20) as client:
            while not self._stop.is_set():
                try:
                    response = client.get(
                        f"{self._api_url}/api/v1/cameras/active", headers=self._headers
                    )
                    response.raise_for_status()
                    self._reconcile(client, response.json())
                except Exception:
                    log.exception("camera reconciliation failed")
                self._stop.wait(self._poll_seconds)

    def _reconcile(self, client: httpx.Client, payloads: list[dict[str, Any]]) -> None:
        desired: dict[str, Camera] = {}
        for payload in payloads:
            stream_id = str(payload.get("stream_id") or "")
            raw_uri = str(payload.get("rtsp_url") or "").strip()
            if not stream_id or not raw_uri:
                continue
            if len(desired) >= self._max_streams:
                log.error("camera limit reached (%d); skipping %s", self._max_streams, stream_id)
                continue
            try:
                desired[stream_id] = camera_from_api(payload, resolve_source(raw_uri))
            except Exception:
                log.exception("cannot resolve camera %s", stream_id)
                if stream_id in self._active:
                    desired[stream_id] = self._active[stream_id]

        for stream_id, old in list(self._active.items()):
            new = desired.get(stream_id)
            if new is None or new.uri != old.uri:
                self._post(client, "remove", old)
                self._active.pop(stream_id, None)
                self._registry.remove_camera(stream_id)

        for stream_id, camera in desired.items():
            self._registry.set_camera(camera)
            if stream_id not in self._active:
                self._post(client, "add", camera)
                self._active[stream_id] = camera
            else:
                self._active[stream_id] = camera

    def _post(self, client: httpx.Client, action: str, camera: Camera) -> None:
        response = client.post(
            f"{self._rest_url}/api/v1/stream/{action}",
            json={
                "key": "sensor",
                "value": {
                    "camera_id": camera.stream_id,
                    "camera_name": camera.name,
                    "camera_url": camera.uri,
                    "change": f"camera_{action}",
                },
            },
        )
        response.raise_for_status()
        log.info("camera %s: %s", action, camera.stream_id)
