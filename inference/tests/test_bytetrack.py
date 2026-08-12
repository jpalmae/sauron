import numpy as np
import pytest

from sauron_inference.config import TrackerConfig
from sauron_inference.tracking.bytetrack import BYTETracker, STrack, fuse_score
from sauron_inference.types import Detection


def det(cx, cy, w=60, h=40, score=0.9, cls=2, name="car"):
    return Detection(
        bbox=np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], dtype=np.float32),
        score=score,
        class_id=cls,
        class_name=name,
    )


@pytest.fixture(autouse=True)
def reset_ids():
    STrack.reset_ids()
    yield
    STrack.reset_ids()


def test_single_object_keeps_id_across_frames():
    tracker = BYTETracker(TrackerConfig(), frame_rate=15)
    ids = set()
    for f in range(10):
        tracks = tracker.update([det(100 + f * 5, 200)])
        assert len(tracks) == 1
        ids.add(tracks[0].track_id)
    assert len(ids) == 1


def test_two_objects_get_distinct_ids():
    tracker = BYTETracker(TrackerConfig(), frame_rate=15)
    ids = set()
    for f in range(10):
        tracks = tracker.update([det(100 + f * 5, 200), det(500 - f * 5, 400)])
        assert len(tracks) == 2
        ids.update(t.track_id for t in tracks)
    assert len(ids) == 2


def test_occluded_object_recovers_same_id():
    tracker = BYTETracker(TrackerConfig(max_time_lost=30), frame_rate=15)
    first_id = None
    for f in range(5):
        tracks = tracker.update([det(100 + f * 2, 200)])
        first_id = tracks[0].track_id
    for _ in range(10):  # occlusion: no detections
        tracker.update([])
    tracks = tracker.update([det(115, 200)])
    assert len(tracks) == 1
    assert tracks[0].track_id == first_id


def test_low_confidence_detections_do_not_spawn_tracks():
    tracker = BYTETracker(TrackerConfig(high_thresh=0.5, low_thresh=0.1), frame_rate=15)
    tracks = tracker.update([det(100, 200, score=0.3)])
    assert tracks == []


def test_lost_track_removed_after_max_time_lost():
    cfg = TrackerConfig(max_time_lost=5)
    tracker = BYTETracker(cfg, frame_rate=15)
    tracker.update([det(100, 200)])
    for _ in range(10):
        tracker.update([])
    assert tracker.lost == []
    assert len(tracker.removed) >= 1


def test_track_history_grows_and_bounds():
    cfg = TrackerConfig(history_size=5)
    tracker = BYTETracker(cfg, frame_rate=15)
    for f in range(20):
        tracks = tracker.update([det(100 + f, 200)])
    history = list(tracks[0].history)
    assert len(history) <= 5
    assert history[-1] == tracks[0].centroid


def test_velocity_reported_after_motion():
    tracker = BYTETracker(TrackerConfig(), frame_rate=15)
    for f in range(5):
        tracks = tracker.update([det(100 + f * 10, 200)])
    vx, vy = tracks[0].velocity
    assert vx > 0
    assert abs(vy) < abs(vx)


def test_score_fusion_does_not_match_disjoint_boxes():
    # IoU distance 1.0 must remain an impossible match even at high confidence.
    candidate = STrack(np.array([0, 0, 10, 10]), 0.99, 2, "car")
    fused = fuse_score(np.array([[1.0]]), [candidate])
    assert fused[0, 0] == pytest.approx(1.0)


def test_tracker_does_not_reuse_id_across_classes():
    tracker = BYTETracker(TrackerConfig(), frame_rate=15)
    car = tracker.update([det(100, 200, cls=2, name="car")])[0]
    bus = tracker.update([det(100, 200, cls=5, name="bus")])[0]
    assert bus.track_id != car.track_id
    assert bus.class_name == "bus"
