import pytest
import yaml

from sauron_inference.config import load_config
from sauron_inference.models import (
    CATALOG,
    DEFAULT_MODEL,
    engine_path,
    model_imgsz,
    onnx_path,
    validate_model,
)


def test_catalog_complete():
    assert set(CATALOG) == {
        "yolov8n", "yolov8s", "yolov8m", "yolov8s-1280", "yolov8m-1280",
        "yolo11n", "yolo11s", "yolov8n-pose",
    }
    for info in CATALOG.values():
        assert info.onnx_file.endswith(".onnx")
        assert info.engine_file.endswith("_fp16.engine")
        assert info.imgsz in (640, 1280)


def test_validate_model():
    assert validate_model("yolo11n") == "yolo11n"
    with pytest.raises(ValueError, match="unknown model"):
        validate_model("yolov9x")


def test_paths():
    assert onnx_path("yolov8m") == "models/yolov8m.onnx"
    assert engine_path("yolo11s") == "models/yolo11s_fp16.engine"
    assert onnx_path("yolov8n", "/app/models") == "/app/models/yolov8n.onnx"
    assert onnx_path("yolov8s-1280") == "models/yolov8s_1280.onnx"
    assert engine_path("yolov8m-1280") == "models/yolov8m_1280_fp16.engine"


def test_model_imgsz():
    assert model_imgsz("yolov8s") == 640
    assert model_imgsz("yolov8s-1280") == 1280
    assert model_imgsz("yolov8m-1280") == 1280
    assert model_imgsz("yolov8n-pose") == 640


def _write(tmp_path, data):
    p = tmp_path / "pipeline.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_model_resolution_default_and_override(tmp_path):
    data = {
        "defaults": {"model": "yolov8s"},
        "streams": [
            {"id": "a", "source": "rtsp://x"},
            {"id": "b", "source": "rtsp://y", "model": "yolo11s"},
        ],
    }
    cfg = load_config(_write(tmp_path, data))
    assert cfg.streams[0].resolved_model(cfg.defaults) == "yolov8s"
    assert cfg.streams[1].resolved_model(cfg.defaults) == "yolo11s"


def test_default_model_used_when_unset(tmp_path):
    cfg = load_config(_write(tmp_path, {"streams": [{"id": "a", "source": "rtsp://x"}]}))
    assert cfg.streams[0].resolved_model(cfg.defaults) == DEFAULT_MODEL


def test_unknown_model_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, {"defaults": {"model": "yolov9"}, "streams": [{"id": "a", "source": "x"}]}))
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, {"streams": [{"id": "a", "source": "x", "model": "nope"}]}))
