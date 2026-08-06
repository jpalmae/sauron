from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..schemas import KpiRow

router = APIRouter(prefix="/kpis", tags=["kpis"])

KPIS_SQL = text(
    """
    SELECT date_trunc(:bucket, e.timestamp) AS bucket,
           e.camera_id                       AS camera_id,
           e.metadata->>'vehicle_class'      AS vehicle_class,
           count(*)                          AS total_count,
           avg((e.metadata->>'speed_kmh')::float) AS avg_speed_kmh,
           0.0                               AS congestion_minutes
    FROM analytics_events e
    WHERE e.event_type = 'LINE_CROSSING'
      AND (:camera_id IS NULL OR e.camera_id = :camera_id)
      AND e.timestamp >= :since AND e.timestamp <= :until
    GROUP BY 1, 2, 3
    UNION ALL
    SELECT date_trunc(:bucket, e.timestamp),
           e.camera_id,
           NULL,
           0,
           NULL,
           sum(coalesce((e.metadata->>'sustained_seconds')::float, 0)) / 60.0
    FROM analytics_events e
    WHERE e.event_type = 'CONGESTION'
      AND (:camera_id IS NULL OR e.camera_id = :camera_id)
      AND e.timestamp >= :since AND e.timestamp <= :until
    GROUP BY 1, 2, 3
    ORDER BY 1 DESC
    """
)


@router.get("", response_model=list[KpiRow])
async def get_kpis(
    session: AsyncSession = Depends(get_session),
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
