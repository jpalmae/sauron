import pytest
import yaml

from sauron_inference.config import load_config


def _write(tmp_path, data):
    p = tmp_path / "pipeline.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


def test_load_example_config():
    cfg = load_config("configs/pipeline.example.yaml")
    assert len(cfg.streams) == 2
    assert cfg.defaults.confidence_threshold == 0.5
    assert cfg.defaults.classes[2] == "car"
    assert cfg.streams[0].type == "rtsp"


def test_duplicate_stream_ids_rejected(tmp_path):
    data = {
        "streams": [
            {"id": "a", "source": "rtsp://x"},
            {"id": "a", "source": "rtsp://y"},
        ]
    }
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, data))


def test_device_assignment_round_robin(tmp_path):
    data = {
        "devices": [0, 1],
        "streams": [
            {"id": "a", "source": "rtsp://x"},
            {"id": "b", "source": "rtsp://y"},
            {"id": "c", "source": "rtsp://z", "device_id": 1},
        ],
    }
    cfg = load_config(_write(tmp_path, data))
    assert cfg.device_for(0, cfg.streams[0]) == 0
    assert cfg.device_for(1, cfg.streams[1]) == 1
    assert cfg.device_for(2, cfg.streams[2]) == 1


def test_stream_overrides_defaults(tmp_path):
    data = {
        "defaults": {"confidence_threshold": 0.5},
        "streams": [
            {"id": "a", "source": "rtsp://x", "confidence_threshold": 0.7},
            {"id": "b", "source": "rtsp://y"},
        ],
    }
    cfg = load_config(_write(tmp_path, data))
    assert cfg.streams[0].resolved_confidence(cfg.defaults) == 0.7
    assert cfg.streams[1].resolved_confidence(cfg.defaults) == 0.5


def test_tracker_threshold_validation(tmp_path):
    data = {
        "defaults": {"tracker": {"high_thresh": 1.5}},
        "streams": [{"id": "a", "source": "rtsp://x"}],
    }
    with pytest.raises(ValueError):
        load_config(_write(tmp_path, data))
