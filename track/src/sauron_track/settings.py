from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return int(default)


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return float(default)


class Settings:
    def __init__(self) -> None:
        self.redis_url = os.getenv("SAURON_REDIS_URL", "redis://redis:6379/0")
        self.api_url = os.getenv("SAURON_API_URL", "http://api:8000/api/v1").rstrip("/")
        self.ingest_token = os.getenv("SAURON_INGEST_TOKEN", "")
        self.health_port = _int("SAURON_TRACK_HEALTH_PORT", 8094)
        self.model_name = os.getenv("SAURON_TRACK_MODEL", "yolo11s.pt")
        self.tracker = os.getenv("SAURON_TRACK_TRACKER", "bytetrack.yaml")
        self.device = _int("SAURON_TRACK_DEVICE", 0)
        self.conf = _float("SAURON_TRACK_CONF", 0.30)
        self.imgsz = _int("SAURON_TRACK_IMGSZ", 960)
        self.scooter_min_kmh = _float("SAURON_TRACK_SCOOTER_MIN_KMH", 14.0)
        self.frame_streams = dict(
            pair.split("=", 1)
            for pair in os.getenv("SAURON_TRACK_FRAME_STREAMS", "cam-119=cam-119-hd").split(",")
            if "=" in pair
        )
        self.iou = _float("SAURON_TRACK_IOU", 0.5)
        self.target_fps = _float("SAURON_TRACK_FPS", 20.0)
        # clases COCO: person, bicycle, car, motorcycle, bus, truck, dog
        self.classes = [
            int(c)
            for c in os.getenv(
                "SAURON_TRACK_CLASSES", "0,1,2,3,5,7,16"
            ).split(",")
            if c.strip()
        ]
        self.cameras = [
            c.strip()
            for c in os.getenv("SAURON_TRACK_CAMERAS", "cam-119").split(",")
            if c.strip()
        ]
        self.go2rtc_api = os.getenv(
            "SAURON_TRACK_GO2RTC_API", "http://go2rtc:1984"
        ).rstrip("/")
        # espacio de referencia de las lineas ROI (el muxer de DS escala a esto)
        self.ref_width = _int("SAURON_TRACK_REF_WIDTH", 1280)
        self.ref_height = _int("SAURON_TRACK_REF_HEIGHT", 720)
        self.cooldown_s = _float("SAURON_TRACK_COOLDOWN_S", 2.0)


def load() -> Settings:
    return Settings()
