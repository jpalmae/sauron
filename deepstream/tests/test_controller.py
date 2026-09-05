from unittest.mock import Mock

from sauron_deepstream.controller import SourceController, camera_shard
from sauron_deepstream.registry import CameraRegistry


def test_camera_sharding_is_stable_and_bounded():
    assignments = [camera_shard(f"camera-{index}", 3) for index in range(100)]
    assert assignments == [camera_shard(f"camera-{index}", 3) for index in range(100)]
    assert set(assignments) == {0, 1, 2}


def test_process_restarts_only_when_every_active_source_failed():
    metrics = Mock()
    metrics.recovery_candidates.return_value = []
    restart_process = Mock()
    controller = SourceController(
        api_url="http://api",
        ingest_token="",
        rest_port=9010,
        poll_seconds=15,
        max_streams=20,
        shard_index=0,
        shard_count=1,
        registry=CameraRegistry(),
        metrics=metrics,
        stale_seconds=45,
        recovery_cooldown=45,
        recovery_attempts=3,
        restart_process=restart_process,
    )
    controller._active = {"cam-failed": Mock(), "cam-live": Mock()}

    metrics.failed_camera_ids.return_value = ["cam-failed"]
    controller._recover_stalled_sources(Mock())
    restart_process.assert_not_called()

    metrics.failed_camera_ids.return_value = ["cam-failed", "cam-live"]
    controller._recover_stalled_sources(Mock())
    restart_process.assert_called_once()
