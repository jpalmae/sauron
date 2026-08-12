from sauron_deepstream.domain import Frame, ROIConfig, TrackedObject
from sauron_deepstream.rules import RulesEngine


def _track(object_id: int, point: tuple[float, float], history=None, velocity=(0.0, 0.0)):
    return TrackedObject(
        object_id=object_id,
        camera_id="cam",
        class_name="car",
        class_id=0,
        bbox=(point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5),
        score=0.9,
        centroid=point,
        velocity=velocity,
        track_history=history or [point],
        frame_seq=1,
        timestamp=1.0,
    )


def test_line_crossing_emits_one_count_event():
    roi = ROIConfig.model_validate(
        {"lines": [{"id": "gate", "points": [[50, 0], [50, 100]]}]}
    )
    engine = RulesEngine("cam", roi, fps=10)

    assert engine.process(Frame("cam", 1, 1.0), [_track(7, (40, 50))]) == []
    events = engine.process(Frame("cam", 2, 1.1), [_track(7, (60, 50))])

    assert len(events) == 1
    assert str(events[0].event_type) == "LINE_CROSSING"
    assert events[0].metadata["vehicle_class"] == "car"
    assert engine.process(Frame("cam", 3, 1.2), [_track(7, (40, 50))]) == []


def test_stopped_vehicle_uses_tracker_time():
    roi = ROIConfig.model_validate(
        {
            "polygons": [
                {
                    "id": "lane",
                    "points": [[0, 0], [100, 0], [100, 100], [0, 100]],
                    "rules": ["stopped"],
                }
            ],
            "thresholds": {"stopped_seconds": 2, "stopped_speed_epsilon": 3},
        }
    )
    engine = RulesEngine("cam", roi, fps=10)

    assert engine.process(Frame("cam", 1, 1.0), [_track(4, (50, 50))]) == []
    events = engine.process(Frame("cam", 2, 3.1), [_track(4, (50, 50))])

    assert len(events) == 1
    assert str(events[0].event_type) == "STOPPED_VEHICLE"


def test_source_domain_has_no_pixel_evidence_fields():
    event = RulesEngine(
        "cam", ROIConfig.model_validate({"lines": [{"id": "x", "points": [[0, 0], [1, 0]]}]})
    )
    assert event.camera_id == "cam"
