from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from .metrics import Metrics
from .registry import Camera, CameraRegistry, camera_from_api
from .sources import resolve_source

log = logging.getLogger(__name__)


def camera_shard(stream_id: str, shard_count: int) -> int:
    digest = hashlib.sha256(stream_id.encode()).digest()
    return int.from_bytes(digest[:8], "big") % shard_count


class SourceController:
    """Reconcile API cameras with nvmultiurisrcbin's built-in REST API."""

    def __init__(
        self,
        api_url: str,
        ingest_token: str,
        rest_port: int,
        poll_seconds: float,
        max_streams: int,
        shard_index: int,
        shard_count: int,
        registry: CameraRegistry,
        metrics: Metrics,
        stale_seconds: float,
        recovery_cooldown: float,
        recovery_attempts: int,
        restart_process: Callable[[], None] | None = None,
    ) -> None:
        self._api_url = api_url
        self._headers = {"Authorization": f"Bearer {ingest_token}"} if ingest_token else {}
        self._rest_url = f"http://127.0.0.1:{rest_port}"
        self._poll_seconds = poll_seconds
        self._max_streams = max_streams
        self._shard_index = shard_index
        self._shard_count = shard_count
        self._registry = registry
        self._metrics = metrics
        self._stale_seconds = stale_seconds
        self._recovery_cooldown = recovery_cooldown
        self._recovery_attempts = recovery_attempts
        self._restart_process = restart_process
        self._restart_requested = False
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
            if stream_id and camera_shard(stream_id, self._shard_count) != self._shard_index:
                continue
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

        self._metrics.set_active_cameras(desired)

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
                if not self._wait_until_bound(stream_id):
                    log.warning("camera source binding timed out: %s", stream_id)
                self._active[stream_id] = camera
            else:
                self._active[stream_id] = camera

        self._recover_stalled_sources(client)

    def _recover_stalled_sources(self, client: httpx.Client) -> None:
        for stream_id in self._metrics.recovery_candidates(
            self._stale_seconds,
            self._recovery_cooldown,
            self._recovery_attempts,
        ):
            camera = self._active.get(stream_id)
            if camera is None:
                continue
            attempt = self._metrics.begin_recovery(stream_id)
            log.warning(
                "camera %s has no fresh frames; restarting source (attempt %d/%d)",
                stream_id,
                attempt,
                self._recovery_attempts,
            )
            try:
                self._post(client, "remove", camera)
            except Exception:
                log.exception("camera source removal failed during recovery: %s", stream_id)
            self._active.pop(stream_id, None)
            self._registry.remove_camera(stream_id)
            if self._stop.wait(1):
                return
            self._registry.set_camera(camera)
            try:
                self._post(client, "add", camera)
                self._active[stream_id] = camera
                if not self._wait_until_bound(stream_id):
                    log.warning("camera recovery binding timed out: %s", stream_id)
            except Exception:
                log.exception("camera source addition failed during recovery: %s", stream_id)

        failed = self._metrics.failed_camera_ids(
            self._stale_seconds,
            self._recovery_attempts,
        )
        if failed and not self._restart_requested:
            self._restart_requested = True
            log.critical(
                "source recovery budget exhausted for %s; restarting DeepStream process",
                ", ".join(failed),
            )
            if self._restart_process is not None:
                self._restart_process()

    def _wait_until_bound(self, stream_id: str, timeout: float = 20.0) -> bool:
        """Wait for nvmultiurisrcbin before submitting another source.

        Its REST endpoint acknowledges an addition before the source is fully
        attached. A second request during that window can otherwise be
        accepted without either source being bound to the pipeline.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._registry.is_bound(stream_id):
                return True
            if self._stop.wait(0.1):
                return False
        return self._registry.is_bound(stream_id)

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
