import numpy as np

from sauron_inference.config import (
    HomographyConfig,
    LineConfig,
    PolygonConfig,
    ROIConfig,
    ThresholdsConfig,
)
from sauron_inference.rules.engine import RulesEngine
from sauron_inference.rules.events import EventType
from sauron_inference.types import Frame, TrackedObject

FPS = 15


def make_track(oid, cx, cy, ts, vx=0.0):
    return TrackedObject(
        object_id=oid,
        camera_id="cam-e",
        class_name="car",
        class_id=2,
        bbox=(cx - 30, cy - 20, cx + 30, cy + 20),
        score=0.9,
        centroid=(cx, cy),
        velocity=(vx, 0.0),
        track_history=[(cx - 5 * vx, cy), (cx, cy)],
        frame_seq=int(ts * FPS),
        timestamp=ts,
    )


def roi_config():
    return ROIConfig(
        lines=[LineConfig(id="L1", points=[[0, 100], [1000, 100]])],
        polygons=[
            PolygonConfig(
                id="lane1",
                points=[[0, 0], [1000, 0], [1000, 500], [0, 500]],
                rules=["stopped", "congestion"],
            ),
            PolygonConfig(
                id="parking1",
                kind="parking",
                points=[[0, 500], [300, 500], [300, 700], [0, 700]],
                rules=["stopped"],
            ),
        ],
        homography=HomographyConfig(
            src_points=[[0, 0], [1000, 0], [1000, 500], [0, 500]],
            dst_points=[[0, 0], [100, 0], [100, 50], [0, 50]],
        ),
        thresholds=ThresholdsConfig(stopped_seconds=1.0, congestion_occupancy=0.9),
    )


def frame(ts):
    return Frame(
        camera_id="cam-e", seq=int(ts * FPS), image=np.zeros((720, 1280, 3), np.uint8), timestamp=ts
    )


def test_engine_builds_rules_from_config():
    engine = RulesEngine("cam-e", roi_config(), fps=FPS)
    assert len(engine.rules) == 4  # 1 line + lane(stopped, congestion) + parking(stopped)
    assert engine.ctx.speed_estimator is not None


def test_engine_without_roi_builds_nothing():
    engine = RulesEngine("cam-e", ROIConfig(), fps=FPS)
    assert engine.rules == []
    assert engine.process(frame(0.0), []) == []


def test_engine_dispatches_events_with_snapshot():
    engine = RulesEngine("cam-e", roi_config(), fps=FPS)
    # stationary car inside lane1 -> stopped alert after 1s
    events = []
    ts = 0.0
    while ts <= 1.5:
        events += engine.process(frame(ts), [make_track(1, 500, 250, ts)])
        ts += 1 / FPS
    stopped = [e for e in events if e.event_type == EventType.STOPPED_VEHICLE]
    assert len(stopped) == 1
    assert stopped[0].snapshot is not None
    d = stopped[0].to_dict()
    assert d["camera_id"] == "cam-e"
    assert d["has_snapshot"] is True
    assert "snapshot" not in d  # raw frames must not leak into payloads


def test_engine_can_run_metadata_only_without_visual_evidence():
    engine = RulesEngine(
        "cam-e", roi_config(), fps=FPS, attach_visual_evidence=False
    )
    events = []
    for index in range(24):
        ts = index / FPS
        events += engine.process(frame(ts), [make_track(1, 500, 250, ts)])
    stopped = [e for e in events if e.event_type == EventType.STOPPED_VEHICLE]
    assert len(stopped) == 1
    assert stopped[0].snapshot is None
    assert "signature" not in stopped[0].metadata


def test_engine_enriches_speed():
    engine = RulesEngine("cam-e", roi_config(), fps=FPS)
    t1 = make_track(1, 500, 250, 0.0, vx=10.0)
    engine.process(frame(0.0), [t1])
    assert t1.speed_kmh is None
    t2 = make_track(1, 510, 250, 1 / FPS, vx=10.0)
    engine.process(frame(1 / FPS), [t2])
    assert t2.speed_kmh is not None
    assert 40 < t2.speed_kmh < 70  # 10 px/frame @15fps over 10px/m -> 54 km/h


def test_line_crossing_event_includes_speed():
    engine = RulesEngine("cam-e", roi_config(), fps=FPS)
    events = []
    ts = 0.0
    cy = 60.0
    for i in range(8):
        t = make_track(1, 500, cy + i * 10, ts)
        events += engine.process(frame(ts), [t])
        ts += 1 / FPS
    crossing = [e for e in events if e.event_type == EventType.LINE_CROSSING]
    assert len(crossing) == 1
    assert crossing[0].metadata["vehicle_class"] == "car"
    assert "speed_kmh" in crossing[0].metadata


def test_periodic_occupancy_metrics_do_not_store_visual_evidence():
    roi = ROIConfig(
        polygons=[
            PolygonConfig(
                id="people",
                points=[[0, 0], [1000, 0], [1000, 500], [0, 500]],
                rules=["occupancy", "chair_occupancy"],
            )
        ]
    )
    events = RulesEngine("cam-e", roi, fps=FPS).process(frame(0.0), [])
    assert {event.event_type for event in events} == {
        EventType.OCCUPANCY,
        EventType.CHAIR_OCCUPANCY,
    }
    assert all(event.snapshot is None for event in events)
