import numpy as np
import pytest

from sauron_inference.config import (
    HomographyConfig,
    LineConfig,
    PolygonConfig,
    ThresholdsConfig,
)
from sauron_inference.rules.base import RuleContext
from sauron_inference.rules.congestion import CongestionRule
from sauron_inference.rules.events import EventType, Priority
from sauron_inference.rules.line_crossing import LineCrossingRule
from sauron_inference.rules.speed import SpeedEstimator
from sauron_inference.rules.stopped_vehicle import StoppedVehicleRule
from sauron_inference.rules.wrong_way import WrongWayRule
from sauron_inference.types import Frame, TrackedObject

FPS = 15
TH = ThresholdsConfig(
    stopped_seconds=2.0,
    stopped_speed_epsilon=3.0,
    wrong_way_cosine=-0.7,
    wrong_way_seconds=1.0,
    congestion_occupancy=0.5,
    congestion_seconds=2.0,
    congestion_cooldown_s=10.0,
)
CTX = RuleContext(camera_id="cam-t", fps=FPS, thresholds=TH)


def frame(ts: float) -> Frame:
    return Frame(
        camera_id="cam-t", seq=int(ts * FPS), image=np.zeros((720, 1280, 3), np.uint8), timestamp=ts
    )


def track(
    oid: int,
    cx: float,
    cy: float,
    ts: float,
    vx: float = 0.0,
    vy: float = 0.0,
    cls: str = "car",
    history: list | None = None,
    bbox_size: tuple[float, float] = (60, 40),
) -> TrackedObject:
    w, h = bbox_size
    return TrackedObject(
        object_id=oid,
        camera_id="cam-t",
        class_name=cls,
        class_id=2,
        bbox=(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2),
        score=0.9,
        centroid=(cx, cy),
        velocity=(vx, vy),
        track_history=history if history is not None else [(cx, cy)],
        frame_seq=int(ts * FPS),
        timestamp=ts,
    )


class TestLineCrossing:
    rule = LineCrossingRule(LineConfig(id="L1", points=[[0, 100], [1000, 100]]))

    def test_crossing_emits_once(self):
        events = []
        for i in range(6):
            t = track(oid=1, cx=500, cy=80 + i * 10, ts=i / FPS)
            events += self.rule.process(frame(i / FPS), [t], CTX)
        assert len(events) == 1
        e = events[0]
        assert e.event_type == EventType.LINE_CROSSING
        assert e.priority == Priority.INFO
        assert e.object_id == 1
        assert e.metadata["line_id"] == "L1"

    def test_no_crossing_no_event(self):
        for i in range(6):
            t = track(oid=2, cx=500, cy=200 + i * 5, ts=i / FPS)
            assert self.rule.process(frame(i / FPS), [t], CTX) == []

    def test_direction_filter(self):
        rule = LineCrossingRule(
            LineConfig(id="L2", points=[[0, 100], [1000, 100]], direction=[0, -1])
        )
        # moving down (+y): against the direction vector -> "reverse"
        events = []
        for i in range(6):
            t = track(oid=3, cx=500, cy=80 + i * 10, ts=i / FPS)
            events += rule.process(frame(i / FPS), [t], CTX)
        assert len(events) == 1
        assert events[0].metadata["direction"] == "reverse"

    def test_class_filter(self):
        rule = LineCrossingRule(
            LineConfig(id="L3", points=[[0, 100], [1000, 100]], classes=["truck"])
        )
        events = []
        for i in range(6):
            t = track(oid=4, cx=500, cy=80 + i * 10, ts=i / FPS, cls="car")
            events += rule.process(frame(i / FPS), [t], CTX)
        assert events == []


class TestStoppedVehicle:
    poly = PolygonConfig(
        id="lane1", points=[[0, 0], [500, 0], [500, 500], [0, 500]], rules=["stopped"]
    )
    rule = StoppedVehicleRule(poly)

    def test_stationary_triggers_after_threshold(self):
        events = []
        ts = 0.0
        while ts <= 3.0:
            t = track(oid=1, cx=250, cy=250, ts=ts, vx=0.05, vy=0.0)
            events += self.rule.process(frame(ts), [t], CTX)
            ts += 1 / FPS
        assert len(events) == 1
        assert events[0].event_type == EventType.STOPPED_VEHICLE
        assert events[0].priority == Priority.WARNING
        assert events[0].metadata["stopped_seconds"] >= TH.stopped_seconds

    def test_moving_vehicle_no_alert(self):
        ts = 0.0
        while ts <= 4.0:
            t = track(oid=2, cx=250, cy=250, ts=ts, vx=5.0, vy=0.0)  # 75 px/s
            assert self.rule.process(frame(ts), [t], CTX) == []
            ts += 1 / FPS

    def test_stationary_outside_polygon_no_alert(self):
        ts = 0.0
        while ts <= 3.0:
            t = track(oid=3, cx=900, cy=600, ts=ts)
            assert self.rule.process(frame(ts), [t], CTX) == []
            ts += 1 / FPS


class TestWrongWay:
    poly = PolygonConfig(
        id="lane-ww",
        points=[[0, 0], [1000, 0], [1000, 500], [0, 500]],
        rules=["wrong_way"],
        direction=[1, 0],
    )
    rule = WrongWayRule(poly)

    def _run(self, x0: float, dx: float, seconds: float, oid: int = 1):
        events = []
        ts = 0.0
        steps = int(seconds * FPS)
        for i in range(steps):
            cx = x0 + dx * i
            hist = [(x0 + dx * max(0, i - 7 + k), 250.0) for k in range(8)]
            t = track(oid=oid, cx=cx, cy=250, ts=ts, history=hist)
            events += self.rule.process(frame(ts), [t], CTX)
            ts += 1 / FPS
        return events

    def test_wrong_way_sustained_triggers_critical(self):
        events = self._run(x0=800, dx=-6.0, seconds=2.0)
        assert len(events) == 1
        assert events[0].event_type == EventType.WRONG_WAY
        assert events[0].priority == Priority.CRITICAL
        assert events[0].metadata["cosine"] < TH.wrong_way_cosine

    def test_correct_direction_no_alert(self):
        assert self._run(x0=100, dx=6.0, seconds=3.0, oid=2) == []

    def test_brief_wrong_movement_no_alert(self):
        assert self._run(x0=800, dx=-6.0, seconds=0.5, oid=3) == []

    def test_requires_direction(self):
        with pytest.raises(ValueError):
            WrongWayRule(
                PolygonConfig(id="p", points=[[0, 0], [10, 0], [10, 10]], rules=["wrong_way"])
            )


class TestCongestion:
    poly = PolygonConfig(
        id="z1", points=[[0, 0], [200, 0], [200, 200], [0, 200]], rules=["congestion"]
    )
    rule = CongestionRule(poly)

    def _congested_tracks(self, ts: float):
        return [
            track(oid=1, cx=60, cy=60, ts=ts, bbox_size=(110, 110)),
            track(oid=2, cx=150, cy=60, ts=ts, bbox_size=(110, 110)),
            track(oid=3, cx=60, cy=150, ts=ts, bbox_size=(110, 110)),
            track(oid=4, cx=150, cy=150, ts=ts, bbox_size=(110, 110)),
        ]

    def test_occupancy_ratio(self):
        occ = self.rule.occupancy(self._congested_tracks(0.0))
        assert occ == 1.0  # 4 * 12100 > 40000 -> clipped

    def test_sustained_congestion_alerts_once_then_cooldown(self):
        events = []
        ts = 0.0
        while ts <= 20.0:
            events += self.rule.process(frame(ts), self._congested_tracks(ts), CTX)
            ts += 0.5
        assert len(events) == 2  # one at ~2s, one after 10s cooldown
        assert events[0].event_type == EventType.CONGESTION
        assert events[0].object_id is None

    def test_free_flow_no_alert(self):
        t = track(oid=1, cx=50, cy=50, ts=0.0, bbox_size=(40, 40))
        assert self.rule.process(frame(0.0), [t], CTX) == []


class TestSpeedEstimator:
    def test_kmh_conversion(self):
        # 10 px == 1 m (dst plane is 100x50 m over a 1000x500 px area)
        est = SpeedEstimator(
            HomographyConfig(
                src_points=[[0, 0], [1000, 0], [1000, 500], [0, 500]],
                dst_points=[[0, 0], [100, 0], [100, 50], [0, 50]],
            )
        )
        assert est.update(1, (500, 250), 0.0) is None
        # 10 px/frame at 15 fps -> 15 m/s -> 54 km/h
        speed = est.update(1, (510, 250), 1 / FPS)
        assert speed == pytest.approx(54.0, rel=0.01)

    def test_purge(self):
        est = SpeedEstimator(
            HomographyConfig(
                src_points=[[0, 0], [100, 0], [100, 100], [0, 100]],
                dst_points=[[0, 0], [10, 0], [10, 10], [0, 10]],
            )
        )
        est.update(1, (50, 50), 0.0)
        est.purge(set())
        assert est._last == {}
