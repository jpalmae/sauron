from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StreamSpec:
    camera_id: str
    source: str
    crop: tuple[int, int, int, int] | None = None


def parse_streams(value: str) -> tuple[StreamSpec, ...]:
    streams: list[StreamSpec] = []
    seen: set[str] = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        camera_id, separator, source = item.partition("=")
        camera_id = camera_id.strip()
        source = source.strip() if separator else camera_id
        if not camera_id or not source:
            raise ValueError(f"invalid ALPR stream mapping: {item!r}")
        if camera_id in seen:
            raise ValueError(f"duplicate ALPR camera id: {camera_id}")
        streams.append(StreamSpec(camera_id=camera_id, source=source))
        seen.add(camera_id)
    if not streams:
        raise ValueError("SAURON_ALPR_STREAMS must contain at least one camera")
    return tuple(streams)


def _float_env(name: str, default: float, minimum: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True, slots=True)
class Settings:
    streams: tuple[StreamSpec, ...]
    go2rtc_url: str
    rtsp_base: str
    target_fps: float
    stale_after_s: float
    detector_model: str
    detector_confidence: float
    ocr_model: str
    ocr_confidence: float
    device: str
    event_cooldown_s: float
    api_url: str
    ingest_token: str
    access_user: str
    access_password: str
    vehicle_api_url: str
    vehicle_api_key: str
    vehicle_include_owner: bool
    vehicle_provider: str
    vehicle_cameras: str
    validate_plate: bool
    query_det_conf: float
    query_ocr_conf: float
    matricula_username: str
    matricula_key: str
    matricula_endpoint: str
    matricula_operation: str
    region: str
    reconcile_seconds: float
    bestshot_wait_s: float
    bestshot_conf: float

    @classmethod
    def from_env(cls) -> Settings:
        device = os.getenv("SAURON_ALPR_DEVICE", "cuda").strip().lower()
        if device not in {"cpu", "cuda"}:
            raise ValueError("SAURON_ALPR_DEVICE must be 'cpu' or 'cuda'")
        return cls(
            streams=parse_streams(
                os.getenv(
                    "SAURON_ALPR_STREAMS",
                    "cam-10,cam-166=cam-166-hd,cam-196,cam-212,"
                    "cam-39=cam-39-hd,cam-75,"
                    "caltrans-i5-43rd=public-i5-43rd,"
                    "caltrans-us50-howe=public-us50-howe",
                )
            ),
            go2rtc_url=os.getenv("SAURON_ALPR_GO2RTC_URL", "http://go2rtc:1984").rstrip("/"),
            rtsp_base=os.getenv("SAURON_ALPR_RTSP_BASE", "rtsp://go2rtc:8554").rstrip("/"),
            target_fps=_float_env("SAURON_ALPR_TARGET_FPS", 2.0, 0.1),
            stale_after_s=_float_env("SAURON_ALPR_STALE_AFTER_S", 30.0, 1.0),
            detector_model=os.getenv(
                "SAURON_ALPR_DETECTOR_MODEL",
                "yolo-v9-s-608-license-plate-end2end",
            ),
            detector_confidence=_float_env("SAURON_ALPR_DETECTOR_CONFIDENCE", 0.25, 0.0),
            ocr_model=os.getenv("SAURON_ALPR_OCR_MODEL", "cct-s-v2-global-model"),
            ocr_confidence=_float_env("SAURON_ALPR_OCR_CONFIDENCE", 0.65, 0.0),
            device=device,
            event_cooldown_s=_float_env("SAURON_ALPR_EVENT_COOLDOWN_S", 30.0, 0.0),
            api_url=os.getenv("SAURON_ALPR_API_URL", "http://api:8000/api/v1").rstrip("/"),
            ingest_token=os.getenv("SAURON_ALPR_INGEST_TOKEN", ""),
            access_user=os.getenv("SAURON_ALPR_USER", ""),
            access_password=os.getenv("SAURON_ALPR_PASSWORD", ""),
            vehicle_api_url=os.getenv(
                "SAURON_ALPR_VEHICLE_API_URL",
                "https://api.boostr.cl/vehicle/{plate}.json",
            ),
            vehicle_api_key=os.getenv("SAURON_ALPR_VEHICLE_API_KEY", ""),
            vehicle_include_owner=_bool_env("SAURON_ALPR_VEHICLE_INCLUDE_OWNER", False),
            vehicle_provider=os.getenv("SAURON_ALPR_VEHICLE_PROVIDER", "").strip().lower(),
            vehicle_cameras=os.getenv("SAURON_ALPR_VEHICLE_CAMERAS", "").strip(),
            validate_plate=_bool_env("SAURON_ALPR_VALIDATE_PLATE", False),
            query_det_conf=_float_env("SAURON_ALPR_QUERY_DET_CONF", 1.0, 0.0),
            query_ocr_conf=_float_env("SAURON_ALPR_QUERY_OCR_CONF", 1.0, 0.0),
            matricula_username=os.getenv("SAURON_ALPR_MATRICULA_USERNAME", "").strip(),
            matricula_key=os.getenv("SAURON_ALPR_MATRICULA_KEY", "").strip(),
            matricula_endpoint=os.getenv(
                "SAURON_ALPR_MATRICULA_ENDPOINT",
                "https://www.regcheck.org.uk/api/reg.asmx",
            ).rstrip("/"),
            matricula_operation=os.getenv("SAURON_ALPR_MATRICULA_OPERATION", "CheckChile").strip(),
            region=os.getenv("SAURON_ALPR_REGION", "").strip(),
            bestshot_wait_s=_float_env("SAURON_ALPR_BESTSHOT_WAIT_S", 4.0, 0.5),
            bestshot_conf=_float_env("SAURON_ALPR_BESTSHOT_CONF", 0.95, 0.5),
            reconcile_seconds=_float_env("SAURON_ALPR_RECONCILE_S", 15.0, 1.0),
        )
