from __future__ import annotations

import logging

import httpx

from .config import DefaultsConfig, DetectorConfig, ROIConfig, StreamConfig

log = logging.getLogger(__name__)


class APICameraSource:
    """Polls the Sauron API for active cameras and maps them to StreamConfigs.

    Enables GUI-driven camera management: cameras added/edited/removed in the
    dashboard are picked up by the inference engine without editing YAML.

    The pipeline YAML still provides the *defaults* (detector backend, tracker,
    classes, capture) — the API is the source of truth for *which* cameras run.
    """

    def __init__(
        self,
        base_url: str,
        ingest_token: str | None,
        defaults: DefaultsConfig,
        target_fps: int = 5,
        poll_interval: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ingest_token = ingest_token
        self.defaults = defaults
        self.target_fps = target_fps
        self.poll_interval = poll_interval
        self._client = httpx.Client(base_url=self.base_url, timeout=10.0)

    def fetch_streams(self) -> list[StreamConfig]:
        headers = {}
        if self.ingest_token:
            headers["Authorization"] = f"Bearer {self.ingest_token}"
        resp = self._client.get("/api/v1/cameras/active", headers=headers)
        resp.raise_for_status()
        cameras = resp.json()

        streams: list[StreamConfig] = []
        for cam in cameras:
            stream_id = cam.get("stream_id")
            if not stream_id:
                continue
            rtsp = (cam.get("rtsp_url") or "").strip()
            if not rtsp:
                log.debug("skip camera %s: empty rtsp_url", stream_id)
                continue
            roi = None
            if cam.get("roi_config"):
                try:
                    roi = ROIConfig.model_validate(cam["roi_config"])
                except ValueError:
                    log.warning("camera %s: invalid roi_config, ignoring ROI", stream_id)
            streams.append(
                StreamConfig(
                    id=stream_id,
                    name=cam.get("name", stream_id),
                    type="rtsp",
                    source=rtsp,
                    target_fps=self.target_fps,
                    model=cam.get("model") or None,
                    detector=(
                        DetectorConfig(backend=cam["detector"])
                        if cam.get("detector")
                        else None
                    ),
                    roi=roi,
                )
            )
        return streams

    def fetch_engine_config(self) -> tuple[dict, int] | None:
        """Pull GUI-editable engine defaults (backend/model/classes/thresholds)."""
        headers = {}
        if self.ingest_token:
            headers["Authorization"] = f"Bearer {self.ingest_token}"
        try:
            resp = self._client.get("/api/v1/pipeline-config", headers=headers)
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data.get("defaults") or {}, int(data.get("target_fps") or 0)
        except Exception:
            log.debug("engine config fetch failed")
            return None

    def close(self) -> None:
        self._client.close()
