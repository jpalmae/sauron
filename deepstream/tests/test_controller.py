from sauron_deepstream.controller import camera_shard


def test_camera_sharding_is_stable_and_bounded():
    assignments = [camera_shard(f"camera-{index}", 3) for index in range(100)]
    assert assignments == [camera_shard(f"camera-{index}", 3) for index in range(100)]
    assert set(assignments) == {0, 1, 2}
