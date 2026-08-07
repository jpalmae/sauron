from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..db import get_session
from ..models import User
from ..schemas import KpiRow

router = APIRouter(prefix="/kpis", tags=["kpis"])

KPIS_SQL = text(
    """
    SELECT date_trunc((:bucket)::text, h.bucket) AS bucket,
           h.camera_id                       AS camera_id,
           h.vehicle_class                   AS vehicle_class,
           sum(h.total_count)                AS total_count,
           sum(h.avg_speed_kmh * h.total_count) / nullif(sum(h.total_count), 0)
                                             AS avg_speed_kmh,
           sum(h.congestion_minutes)         AS congestion_minutes
    FROM analytics_kpis_hourly h
    WHERE ((:camera_id)::uuid IS NULL OR h.camera_id = (:camera_id)::uuid)
      AND h.bucket >= :since AND h.bucket <= :until
    GROUP BY 1, 2, 3
    ORDER BY 1 DESC
    """
)


@router.get("", response_model=list[KpiRow])
async def get_kpis(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
    camera_id: uuid.UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    bucket: str = "hour",
):
    if bucket not in {"hour", "day", "week", "month"}:
        raise HTTPException(422, "bucket must be one of: hour, day, week, month")
    if session.bind is not None and session.bind.dialect.name != "postgresql":
        raise HTTPException(501, "KPIs require PostgreSQL/TimescaleDB")
    params = {
        "bucket": bucket,
        "camera_id": camera_id,
        "since": since or datetime.min.replace(tzinfo=None),
        "until": until or datetime.max.replace(tzinfo=None),
    }
    result = await session.execute(KPIS_SQL, params)
    return [
        KpiRow(
            bucket=row.bucket,
            camera_id=row.camera_id,
            vehicle_class=row.vehicle_class,
            total_count=row.total_count,
            avg_speed_kmh=row.avg_speed_kmh,
            congestion_minutes=float(row.congestion_minutes or 0),
        )
        for row in result
    ]
