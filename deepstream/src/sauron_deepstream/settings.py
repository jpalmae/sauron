from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, default))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _positive_float(name: str, default: float) -> float:
    value = float(os.environ.get(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _shard_index() -> int:
    explicit = os.environ.get("SAURON_DS_SHARD_INDEX")
    if explicit is not None:
        return max(0, int(explicit))
    pod_name = os.environ.get("SAURON_DS_POD_NAME", "")
    ordinal = pod_name.rsplit("-", 1)[-1]
    return int(ordinal) if ordinal.isdigit() else 0


@dataclass(frozen=True, slots=True)
class Settings:
    api_url: str
    ingest_token: str
    redis_url: str
    max_streams: int
    shard_index: int
    shard_count: int
    secondary_batch_size: int
    target_fps: int
    inference_interval: int
    source_poll_seconds: float
    source_stale_seconds: float
    source_recovery_cooldown: float
    source_recovery_attempts: int
    source_rest_port: int
    health_port: int
    mux_width: int
    mux_height: int
    gpu_id: int
    primary_model_path: Path
    primary_labels_path: Path
    vehicle_model_path: Path
    vehicle_labels_path: Path
    engine_dir: Path
    pgie_template: Path
    sgie_template: Path
    tracker_config: Path
    tracker_library: Path

    @classmethod
    def from_env(cls) -> Settings:
        root = Path(os.environ.get("SAURON_DS_ROOT", "/app/deepstream"))
        ds_root = Path("/opt/nvidia/deepstream/deepstream")
        model_cache = Path(os.environ.get("SAURON_DS_MODEL_CACHE", "/models/tao"))
        return cls(
            api_url=os.environ.get("SAURON_API_URL", "http://api:8000").rstrip("/"),
            ingest_token=os.environ.get("SAURON_INGEST_TOKEN", ""),
            redis_url=os.environ.get("SAURON_REDIS_URL", "redis://redis:6379/0"),
            max_streams=_positive_int("SAURON_DS_MAX_STREAMS", 20),
            shard_index=_shard_index(),
            shard_count=_positive_int("SAURON_DS_SHARD_COUNT", 1),
            secondary_batch_size=_positive_int("SAURON_DS_SECONDARY_BATCH", 64),
            target_fps=_positive_int("SAURON_DS_TARGET_FPS", 10),
            inference_interval=max(0, int(os.environ.get("SAURON_DS_INFERENCE_INTERVAL", "0"))),
            source_poll_seconds=_positive_float("SAURON_DS_SOURCE_POLL_S", 15),
            source_stale_seconds=_positive_float("SAURON_DS_SOURCE_STALE_S", 45),
            source_recovery_cooldown=_positive_float("SAURON_DS_RECOVERY_COOLDOWN_S", 45),
            source_recovery_attempts=_positive_int("SAURON_DS_RECOVERY_ATTEMPTS", 3),
            source_rest_port=_positive_int("SAURON_DS_SOURCE_REST_PORT", 9010),
            health_port=_positive_int("SAURON_DS_HEALTH_PORT", 9100),
            mux_width=_positive_int("SAURON_DS_MUX_WIDTH", 1280),
            mux_height=_positive_int("SAURON_DS_MUX_HEIGHT", 720),
            gpu_id=max(0, int(os.environ.get("SAURON_DS_GPU_ID", "0"))),
            primary_model_path=Path(
                os.environ.get(
                    "SAURON_DS_PRIMARY_MODEL",
                    model_cache / "resnet18_trafficcamnet_pruned.onnx",
                )
            ),
            primary_labels_path=Path(
                os.environ.get(
                    "SAURON_DS_PRIMARY_LABELS",
                    model_cache / "trafficcamnet_labels.txt",
                )
            ),
            vehicle_model_path=Path(
                os.environ.get(
                    "SAURON_DS_VEHICLE_MODEL",
                    model_cache / "resnet18_vehicletypenet_pruned.onnx",
                )
            ),
            vehicle_labels_path=Path(
                os.environ.get(
                    "SAURON_DS_VEHICLE_LABELS",
                    model_cache / "vehicletypenet_labels.txt",
                )
            ),
            engine_dir=Path(os.environ.get("SAURON_DS_ENGINE_DIR", "/models/deepstream")),
            pgie_template=Path(
                os.environ.get(
                    "SAURON_DS_PGIE_TEMPLATE", root / "configs/pgie_trafficcamnet.ini.tmpl"
                )
            ),
            sgie_template=Path(
                os.environ.get(
                    "SAURON_DS_SGIE_TEMPLATE", root / "configs/sgie_vehicletypenet.ini.tmpl"
                )
            ),
            tracker_config=Path(
                os.environ.get(
                    "SAURON_DS_TRACKER_CONFIG",
                    ds_root / "samples/configs/deepstream-app/config_tracker_NvDCF_perf.yml",
                )
            ),
            tracker_library=Path(
                os.environ.get(
                    "SAURON_DS_TRACKER_LIBRARY",
                    ds_root / "lib/libnvds_nvmultiobjecttracker.so",
                )
            ),
        )

    def validate_files(self) -> None:
        if self.shard_index >= self.shard_count:
            raise ValueError("SAURON_DS_SHARD_INDEX must be lower than SAURON_DS_SHARD_COUNT")
        for path in (
            self.primary_model_path,
            self.primary_labels_path,
            self.vehicle_model_path,
            self.vehicle_labels_path,
            self.pgie_template,
            self.sgie_template,
            self.tracker_config,
            self.tracker_library,
        ):
            if not path.is_file():
                raise FileNotFoundError(path)

    def render_infer_configs(self) -> tuple[Path, Path]:
        self.engine_dir.mkdir(parents=True, exist_ok=True)
        primary_engine = self.primary_model_path.with_name(
            f"{self.primary_model_path.name}_b{self.max_streams}_gpu{self.gpu_id}_fp16.engine"
        )
        primary = self.pgie_template.read_text().format(
            gpu_id=self.gpu_id,
            batch_size=self.max_streams,
            interval=self.inference_interval,
            model_path=self.primary_model_path,
            engine_path=primary_engine,
            labels_path=self.primary_labels_path,
        )
        pgie_output = self.engine_dir / f"pgie-trafficcamnet-b{self.max_streams}.ini"
        pgie_output.write_text(primary)

        vehicle_engine = self.vehicle_model_path.with_name(
            f"{self.vehicle_model_path.name}_b{self.secondary_batch_size}_gpu{self.gpu_id}_fp16.engine"
        )
        secondary = self.sgie_template.read_text().format(
            gpu_id=self.gpu_id,
            batch_size=self.secondary_batch_size,
            model_path=self.vehicle_model_path,
            engine_path=vehicle_engine,
            labels_path=self.vehicle_labels_path,
        )
        sgie_output = self.engine_dir / f"sgie-vehicletypenet-b{self.secondary_batch_size}.ini"
        sgie_output.write_text(secondary)
        return pgie_output, sgie_output
