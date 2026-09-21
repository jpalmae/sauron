from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return float(default)


class Settings:
    """Environment-driven settings for the relate sidecar."""

    def __init__(self) -> None:
        self.redis_url = os.getenv("SAURON_REDIS_URL", "redis://redis:6379/0")
        self.api_url = os.getenv("SAURON_API_URL", "http://api:8000/api/v1").rstrip("/")
        self.ingest_token = os.getenv("SAURON_INGEST_TOKEN", "")
        self.health_port = _int("SAURON_RELATE_HEALTH_PORT", 8093)
        self.device = os.getenv("SAURON_RELATE_DEVICE", "cuda")
        self.model_id = os.getenv(
            "SAURON_RELATE_MODEL", "maelic/relsgg-vits16plus"
        )
        self.cameras = [
            c.strip()
            for c in os.getenv("SAURON_RELATE_CAMERAS", "cam-119").split(",")
            if c.strip()
        ]
        self.target_fps = _float("SAURON_RELATE_FPS", 5.0)
        self.score_threshold = _float("SAURON_RELATE_SCORE", 0.20)
        self.topk = _int("SAURON_RELATE_TOPK", 12)
        self.min_frames = _int("SAURON_RELATE_MIN_FRAMES", 2)
        self.cooldown_s = _float("SAURON_RELATE_COOLDOWN_S", 60.0)
        self.capture_url = os.getenv(
            "SAURON_RELATE_CAPTURE_BASE", "rtsp://go2rtc:8554"
        ).rstrip("/")
        self.go2rtc_api = os.getenv("SAURON_RELATE_GO2RTC_API", "http://go2rtc:1984").rstrip("/")
        self.max_objects = _int("SAURON_RELATE_MAX_OBJECTS", 20)


def load() -> Settings:
    return Settings()
