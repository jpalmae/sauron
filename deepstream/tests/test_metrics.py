from sauron_deepstream.metrics import Metrics


def test_camera_liveness_uses_real_frames_and_recovers():
    metrics = Metrics()
    metrics.ready = True
    metrics.set_active_cameras(["cam-1"], now_monotonic=100)

    starting = metrics.health_snapshot(45, 3, now_monotonic=110)
    assert starting["status"] == "degraded"
    assert starting["cameras"]["cam-1"]["state"] == "starting"
    assert metrics.recovery_candidates(45, 45, 3, now_monotonic=144) == []
    assert metrics.recovery_candidates(45, 45, 3, now_monotonic=145) == ["cam-1"]

    assert metrics.begin_recovery("cam-1", now_monotonic=145) == 1
    recovering = metrics.health_snapshot(45, 3, now_monotonic=146)
    assert recovering["cameras"]["cam-1"]["state"] == "recovering"

    metrics.record_frame("cam-1", 2, timestamp=1_700_000_000, now_monotonic=147)
    healthy = metrics.health_snapshot(45, 3, now_monotonic=148)
    assert healthy["status"] == "ok"
    assert healthy["live_cameras"] == 1
    assert healthy["cameras"]["cam-1"]["recovery_attempts"] == 0


def test_health_fails_after_recovery_budget_is_exhausted():
    metrics = Metrics()
    metrics.ready = True
    metrics.set_active_cameras(["cam-1"], now_monotonic=0)

    for attempt, now in enumerate((45, 90, 135), start=1):
        assert metrics.recovery_candidates(45, 45, 3, now_monotonic=now) == ["cam-1"]
        assert metrics.begin_recovery("cam-1", now_monotonic=now) == attempt

    grace = metrics.health_snapshot(45, 3, now_monotonic=179)
    assert grace["status"] == "degraded"
    failed = metrics.health_snapshot(45, 3, now_monotonic=180)
    assert failed["status"] == "unhealthy"
    assert failed["healthy"] is False
    assert failed["cameras"]["cam-1"]["state"] == "failed"
    assert metrics.failed_camera_ids(45, 3, now_monotonic=180) == ["cam-1"]


def test_idle_pipeline_is_healthy():
    metrics = Metrics()
    metrics.ready = True
    assert metrics.health_snapshot(45, 3, now_monotonic=10)["status"] == "ok"
