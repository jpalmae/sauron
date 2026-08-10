from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    name: str
    family: str  # yolov8 | yolo11
    onnx_file: str
    engine_file: str  # fp16 TensorRT engine, built on the GPU host
    recommended_profile: str  # XS | S | M
    size_mb: int


CATALOG: dict[str, ModelInfo] = {
    "yolov8n": ModelInfo("yolov8n", "yolov8", "yolov8n.onnx", "yolov8n_fp16.engine", "XS", 13),
    "yolov8s": ModelInfo("yolov8s", "yolov8", "yolov8s.onnx", "yolov8s_fp16.engine", "XS/S", 45),
    "yolov8m": ModelInfo("yolov8m", "yolov8", "yolov8m.onnx", "yolov8m_fp16.engine", "S/M", 104),
    "yolo11n": ModelInfo("yolo11n", "yolo11", "yolo11n.onnx", "yolo11n_fp16.engine", "XS", 11),
    "yolo11s": ModelInfo("yolo11s", "yolo11", "yolo11s.onnx", "yolo11s_fp16.engine", "XS/S", 38),
    "yolov8n-pose": ModelInfo("yolov8n-pose", "yolov8-pose", "yolov8n-pose.onnx", "yolov8n-pose_fp16.engine", "XS", 13),
}

DEFAULT_MODEL = "yolov8n"


def validate_model(name: str) -> str:
    if name not in CATALOG:
        valid = ", ".join(sorted(CATALOG))
        raise ValueError(f"unknown model '{name}' (valid: {valid})")
    return name


def onnx_path(name: str, models_dir: str = "models") -> str:
    return f"{models_dir}/{CATALOG[validate_model(name)].onnx_file}"


def engine_path(name: str, models_dir: str = "models") -> str:
    return f"{models_dir}/{CATALOG[validate_model(name)].engine_file}"
