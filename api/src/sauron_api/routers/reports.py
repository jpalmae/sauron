from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import AnalyticsEvent, Camera
from .kpis import KPIS_SQL

router = APIRouter(prefix="/reports", tags=["reports"])

MAX_ROWS = 50_000


@router.get("/events.csv")
async def events_csv(
    session: AsyncSession = Depends(get_session),
    camera_id: uuid.UUID | None = None,
    event_type: str | None = None,
    priority: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(MAX_ROWS, le=MAX_ROWS),
):
    """Export filtered events as CSV (reportería)."""
    query = (
        select(AnalyticsEvent, Camera.stream_id)
        .join(Camera, Camera.id == AnalyticsEvent.camera_id)
        .order_by(AnalyticsEvent.timestamp.desc())
        .limit(limit)
    )
    if camera_id:
        query = query.where(AnalyticsEvent.camera_id == camera_id)
    if event_type:
        query = query.where(AnalyticsEvent.event_type == event_type)
    if priority:
        query = query.where(AnalyticsEvent.priority == priority)
    if since:
        query = query.where(AnalyticsEvent.timestamp >= since)
    if until:
        query = query.where(AnalyticsEvent.timestamp <= until)

    result = await session.execute(query)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "timestamp",
            "camera",
            "event_type",
            "priority",
            "confidence",
            "rule_id",
            "object_id",
            "vehicle_class",
            "speed_kmh",
        ]
    )
    for row, stream_id in result.all():
        meta = row.extra or {}
        writer.writerow(
            [
                row.timestamp.isoformat(),
                stream_id,
                row.event_type,
                row.priority,
                row.confidence,
                row.rule_id,
                row.object_id,
                meta.get("vehicle_class", ""),
                meta.get("speed_kmh", ""),
            ]
        )
    buf.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="events.csv"'}
    return StreamingResponse(iter([buf.read()]), media_type="text/csv", headers=headers)


@router.get("/kpis.csv")
async def kpis_csv(
    session: AsyncSession = Depends(get_session),
    camera_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    bucket: str = "hour",
):
    if bucket not in {"hour", "day", "week", "month"}:
        raise HTTPException(422, "bucket must be one of: hour, day, week, month")
    if session.bind is not None and session.bind.dialect.name != "postgresql":
        raise HTTPException(501, "KPI reports require PostgreSQL/TimescaleDB")
    params = {
        "bucket": bucket,
        "camera_id": camera_id,
        "since": since or datetime.min.replace(tzinfo=None),
        "until": until or datetime.max.replace(tzinfo=None),
    }
    result = await session.execute(KPIS_SQL, params)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["bucket", "camera_id", "vehicle_class", "total_count", "avg_speed_kmh", "congestion_minutes"]
    )
    for row in result:
        writer.writerow(
            [
                row.bucket.isoformat(),
                row.camera_id,
                row.vehicle_class or "",
                row.total_count,
                round(row.avg_speed_kmh, 1) if row.avg_speed_kmh is not None else "",
                round(float(row.congestion_minutes or 0), 2),
            ]
        )
    buf.seek(0)
    headers = {"Content-Disposition": 'attachment; filename="kpis.csv"'}
    return StreamingResponse(iter([buf.read()]), media_type="text/csv", headers=headers)
