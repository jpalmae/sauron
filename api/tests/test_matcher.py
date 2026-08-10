import uuid
from datetime import UTC, datetime, timedelta

from sauron_api.db import get_session_factory
from sauron_api.matcher import _cos, maybe_create_travel_time
from sauron_api.models import AnalyticsEvent, Camera, Corridor


def _crossing(camera_id, ts, sig, cls="car"):
    return AnalyticsEvent(
        timestamp=ts,
        camera_id=camera_id,
        event_type="LINE_CROSSING",
        priority="info",
        confidence=0.9,
        rule_id="L1",
        vehicle_class=cls,
        extra={"vehicle_class": cls, "signature": sig},
    )


async def _camera(stream_id):
    async with get_session_factory()() as session:
        cam = Camera(name=stream_id, stream_id=stream_id)
        session.add(cam)
        await session.commit()
        return cam.id


def test_cos():
    assert _cos([1, 0], [1, 0]) == 1.0
    assert _cos([1, 0], [0, 1]) == 0.0
    assert _cos([], []) == 0.0


async def test_travel_time_match():
    cam_a = await _camera(f"corr-a-{uuid.uuid4().hex[:6]}")
    cam_b = await _camera(f"corr-b-{uuid.uuid4().hex[:6]}")
    now = datetime.now(UTC)
    sig = [0.5] * 32 + [0.5] * 32

    async with get_session_factory()() as session:
        session.add(Corridor(
            name="norte-sur", from_camera_id=cam_a, to_camera_id=cam_b,
            distance_m=1200.0, max_travel_s=3600,
        ))
        dep = _crossing(cam_a, now - timedelta(seconds=120), sig)
        session.add(dep)
        await session.commit()

        arrival = _crossing(cam_b, now, [s * 1.02 for s in sig])  # same-ish vehicle
        session.add(arrival)
        await session.flush()

        travel = await maybe_create_travel_time(session, arrival)
        assert travel is not None
        assert travel.event_type == "TRAVEL_TIME"
        assert travel.extra["travel_time_s"] == 120.0
        assert travel.extra["avg_speed_kmh"] == 36.0
        assert travel.extra["similarity"] > 0.8


async def test_no_match_when_signature_differs():
    cam_a = await _camera(f"corr-c-{uuid.uuid4().hex[:6]}")
    cam_b = await _camera(f"corr-d-{uuid.uuid4().hex[:6]}")
    now = datetime.now(UTC)

    async with get_session_factory()() as session:
        session.add(Corridor(
            name="c-d", from_camera_id=cam_a, to_camera_id=cam_b,
            distance_m=500.0, max_travel_s=3600,
        ))
        dep = _crossing(cam_a, now - timedelta(seconds=60), [1.0] + [0.0] * 63)
        session.add(dep)
        await session.flush()
        arrival = _crossing(cam_b, now, [0.0] * 63 + [1.0])  # orthogonal
        session.add(arrival)
        await session.flush()
        assert await maybe_create_travel_time(session, arrival) is None


async def test_no_corridor_no_event():
    cam = await _camera(f"solo-{uuid.uuid4().hex[:6]}")
    async with get_session_factory()() as session:
        arrival = _crossing(cam, datetime.now(UTC), [0.5] * 64)
        session.add(arrival)
        await session.flush()
        assert await maybe_create_travel_time(session, arrival) is None


async def test_expired_window_no_event():
    cam_a = await _camera(f"old-a-{uuid.uuid4().hex[:6]}")
    cam_b = await _camera(f"old-b-{uuid.uuid4().hex[:6]}")
    now = datetime.now(UTC)
    sig = [0.5] * 64

    async with get_session_factory()() as session:
        session.add(Corridor(
            name="old", from_camera_id=cam_a, to_camera_id=cam_b,
            distance_m=1000.0, max_travel_s=300,
        ))
        dep = _crossing(cam_a, now - timedelta(seconds=900), sig)  # > max_travel_s
        session.add(dep)
        await session.flush()
        arrival = _crossing(cam_b, now, sig)
        session.add(arrival)
        await session.flush()
        assert await maybe_create_travel_time(session, arrival) is None
