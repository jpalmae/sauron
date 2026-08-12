from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_admin, require_ingest
from ..config import get_settings
from ..db import get_session
from ..models import AnalyticsEvent, Camera, HourlyKpi, User
from ..schemas import CameraCreate, CameraRead, CameraUpdate

router = APIRouter(prefix="/cameras", tags=["cameras"])

_aioredis = None


def _redis_client():
    global _aioredis
    if _aioredis is None:
        import redis.asyncio as aioredis

        _aioredis = aioredis.from_url(get_settings().redis_url)
    return _aioredis


@router.get("", response_model=list[CameraRead])
async def list_cameras(
    session: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)
):
    result = await session.execute(select(Camera).order_by(Camera.name))
    return result.scalars().all()


@router.post("", response_model=CameraRead, status_code=201)
async def create_camera(
    payload: CameraCreate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    exists = await session.execute(select(Camera).where(Camera.stream_id == payload.stream_id))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(409, f"stream_id '{payload.stream_id}' already exists")
    camera = Camera(**payload.model_dump())
    session.add(camera)
    await session.commit()
    await session.refresh(camera)
    return camera


@router.get("/active", response_model=list[CameraRead])
async def list_active_cameras(
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_ingest),
):
    """Active cameras for the inference engine (ingest token or admin JWT)."""
    result = await session.execute(
        select(Camera).where(Camera.is_active.is_(True)).order_by(Camera.name)
    )
    return result.scalars().all()


@router.get("/{camera_id}", response_model=CameraRead)
async def get_camera(
    camera_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(404, "camera not found")
    return camera


@router.get("/{camera_id}/occupancy")
async def camera_occupancy(
    camera_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Live occupancy numbers for a camera (people-count use case).

    Derived from OCCUPANCY events: current count, peak (today / since start),
    unique people seen, and average dwell of those currently present.
    """
    latest = (
        await session.execute(
            select(AnalyticsEvent)
            .where(
                AnalyticsEvent.camera_id == camera_id,
                AnalyticsEvent.event_type == "OCCUPANCY",
            )
            .order_by(AnalyticsEvent.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    meta = (latest.extra or {}) if latest else {}

    now = datetime.now(UTC)
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since_hour = now - timedelta(hours=1)

    rows = (
        await session.execute(
            select(AnalyticsEvent.timestamp, AnalyticsEvent.extra).where(
                AnalyticsEvent.camera_id == camera_id,
                AnalyticsEvent.event_type == "OCCUPANCY",
                AnalyticsEvent.timestamp >= start_day,
            )
        )
    ).all()

    counts_today: list[int] = []
    counts_hour: list[int] = []
    for ts, extra in rows:
        try:
            c = int((extra or {}).get("count"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        counts_today.append(c)
        if ts >= since_hour:
            counts_hour.append(c)

    peak_today = max(counts_today) if counts_today else None
    avg_hour = round(sum(counts_hour) / len(counts_hour), 1) if counts_hour else None

    chair = (
        await session.execute(
            select(AnalyticsEvent.extra)
            .where(
                AnalyticsEvent.camera_id == camera_id,
                AnalyticsEvent.event_type == "CHAIR_OCCUPANCY",
            )
            .order_by(AnalyticsEvent.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    chair_meta = chair or {}

    return {
        "timestamp": latest.timestamp.isoformat() if latest else None,
        "count": meta.get("count"),
        "by_class": meta.get("by_class"),
        "unique_total": meta.get("unique_total"),
        "avg_dwell_s": meta.get("avg_dwell_s"),
        "peak": meta.get("peak"),
        "peak_today": peak_today,
        "avg_last_hour": avg_hour,
        "posture": meta.get("posture"),
        "sit_to_stand": meta.get("sit_to_stand"),
        "stand_to_sit": meta.get("stand_to_sit"),
        "transitions": meta.get("transitions"),
        "unique_reid": meta.get("unique_reid"),
        "falls": meta.get("falls"),
        "seats": chair_meta.get("seats"),
        "occupied_seats": chair_meta.get("occupied"),
        "free_seats": chair_meta.get("free"),
        "seat_utilization": chair_meta.get("utilization"),
    }


@router.get("/{camera_id}/detections")
async def camera_detections(
    camera_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Latest frame detections (boxes/posture/keypoints) for the live overlay."""
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(404, "camera not found")
    data = await _redis_client().get(f"sauron:detections:{camera.stream_id}")
    if not data:
        return {"objects": []}
    return json.loads(data)


@router.patch("/{camera_id}", response_model=CameraRead)
async def update_camera(
    camera_id: uuid.UUID,
    payload: CameraUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(404, "camera not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(camera, field, value)
    await session.commit()
    await session.refresh(camera)
    return camera


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(
    camera_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    camera = await session.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(404, "camera not found")
    # Remove dependent analytics rows first: FKs to cameras lack ON DELETE
    # CASCADE and analytics_events is a Timescale hypertable, so a plain
    # delete raises a ForeignKeyViolationError.
    await session.execute(delete(AnalyticsEvent).where(AnalyticsEvent.camera_id == camera_id))
    await session.execute(delete(HourlyKpi).where(HourlyKpi.camera_id == camera_id))
    try:
        await session.delete(camera)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "camera still referenced; cannot delete")
