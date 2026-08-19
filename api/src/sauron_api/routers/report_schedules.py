from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_admin
from ..db import get_session
from ..models import Camera, NotificationChannel, NotificationDelivery, ReportSchedule, User
from ..scheduled_reports import next_report_run

router = APIRouter(tags=["operations"])


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    channel_id: uuid.UUID
    camera_id: uuid.UUID | None = None
    frequency: str = Field(pattern="^(daily|weekly|monthly)$")
    hour: int = Field(default=8, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    timezone: str = Field(default="America/Santiago", min_length=1, max_length=64)
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = None
    channel_id: uuid.UUID | None = None
    camera_id: uuid.UUID | None = None
    frequency: str | None = Field(default=None, pattern="^(daily|weekly|monthly)$")
    hour: int | None = Field(default=None, ge=0, le=23)
    minute: int | None = Field(default=None, ge=0, le=59)
    timezone: str | None = None
    enabled: bool | None = None


def _schedule_read(row: ReportSchedule) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "channel_id": str(row.channel_id),
        "camera_id": str(row.camera_id) if row.camera_id else None,
        "frequency": row.frequency,
        "hour": row.hour,
        "minute": row.minute,
        "timezone": row.timezone,
        "enabled": row.enabled,
        "next_run_at": row.next_run_at.isoformat(),
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
    }


@router.get("/report-schedules")
async def list_schedules(
    session: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)
):
    rows = (
        (await session.execute(select(ReportSchedule).order_by(ReportSchedule.name)))
        .scalars()
        .all()
    )
    return [_schedule_read(row) for row in rows]


@router.post("/report-schedules", status_code=201)
async def create_schedule(
    payload: ScheduleCreate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    channel = await session.get(NotificationChannel, payload.channel_id)
    if channel is None:
        raise HTTPException(422, "notification channel not found")
    if payload.camera_id is not None and await session.get(Camera, payload.camera_id) is None:
        raise HTTPException(422, "camera not found")
    try:
        next_run = next_report_run(
            payload.frequency, payload.hour, payload.minute, payload.timezone
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    row = ReportSchedule(**payload.model_dump(), next_run_at=next_run)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _schedule_read(row)


@router.patch("/report-schedules/{schedule_id}")
async def update_schedule(
    schedule_id: uuid.UUID,
    payload: ScheduleUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    row = await session.get(ReportSchedule, schedule_id)
    if row is None:
        raise HTTPException(404, "report schedule not found")
    changes = payload.model_dump(exclude_unset=True)
    if "channel_id" in changes:
        channel = await session.get(NotificationChannel, changes["channel_id"])
        if channel is None:
            raise HTTPException(422, "notification channel not found")
    if changes.get("camera_id") is not None:
        camera = await session.get(Camera, changes["camera_id"])
        if camera is None:
            raise HTTPException(422, "camera not found")
    for field, value in changes.items():
        setattr(row, field, value)
    try:
        row.next_run_at = next_report_run(row.frequency, row.hour, row.minute, row.timezone)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    await session.commit()
    return _schedule_read(row)


@router.delete("/report-schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    row = await session.get(ReportSchedule, schedule_id)
    if row is None:
        raise HTTPException(404, "report schedule not found")
    await session.delete(row)
    await session.commit()


@router.get("/notification-deliveries")
async def list_deliveries(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    query = (
        select(NotificationDelivery).order_by(NotificationDelivery.created_at.desc()).limit(limit)
    )
    if status:
        query = query.where(NotificationDelivery.status == status)
    rows = (await session.execute(query)).scalars().all()
    return [
        {
            "id": str(row.id),
            "channel_id": str(row.channel_id),
            "event_id": str(row.event_id) if row.event_id else None,
            "status": row.status,
            "attempts": row.attempts,
            "next_attempt_at": row.next_attempt_at.isoformat(),
            "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
            "last_error": row.last_error,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
