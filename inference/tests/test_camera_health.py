import time

from sauron_inference.config import DefaultsConfig, PipelineConfig
from sauron_inference.pipeline.manager import PipelineManager
from sauron_inference.rules.events import EventType


class FakePipeline:
    def __init__(self, cid, processed=0):
        self.source = type("S", (), {"camera_id": cid})()
        self.frames_processed = processed
        self.frames_captured = processed
        self.frames_dropped = 0

    @property
    def alive(self):
        return True

    def stop(self):
        pass


def _manager(events, offline_seconds=1.0):
    cfg = PipelineConfig(streams=[], defaults=DefaultsConfig())
    m = PipelineManager(
        cfg,
        on_event=events.append,
        detector_factory=lambda *a, **k: None,
        source_factory=lambda *a, **k: None,
        offline_seconds=offline_seconds,
    )
    return m


def test_offline_event_after_idle_threshold():
    events = []
    m = _manager(events, offline_seconds=0.2)
    m.pipelines = [FakePipeline("cam-x", processed=10)]

    m._check_camera_health()  # primes last_frame + processed_seen
    assert events == []

    time.sleep(0.25)
    m._check_camera_health()  # idle > threshold -> CAMERA_OFFLINE
    assert len(events) == 1
    assert events[0].event_type == EventType.CAMERA_OFFLINE
    assert events[0].priority == "warning"
    assert events[0].metadata["idle_seconds"] >= 0

    # no duplicate while still offline
    m._check_camera_health()
    assert len(events) == 1


def test_online_recovery_event():
    events = []
    m = _manager(events, offline_seconds=0.2)
    m.pipelines = [FakePipeline("cam-y", processed=5)]
    m._check_camera_health()
    time.sleep(0.25)
    m._check_camera_health()
    assert events[0].event_type == EventType.CAMERA_OFFLINE

    # stream recovers: more frames processed
    m.pipelines[0].frames_processed = 20
    m._check_camera_health()
    assert len(events) == 2
    assert events[1].event_type == EventType.CAMERA_ONLINE
    assert events[1].priority == "info"


def test_never_online_stream_does_not_alert_immediately():
    events = []
    m = _manager(events, offline_seconds=0.2)
    m.pipelines = [FakePipeline("cam-z", processed=0)]  # never produced
    time.sleep(0.25)
    m._check_camera_health()
    # sin primer frame no hay baseline; no alerta (podría estar iniciando)
    assert events == []
