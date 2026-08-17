from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..db import get_session
from ..models import AnalyticsEvent, Camera, User
from ..storage import get_storage
from ..synopsis import build_contact_sheet, fmt_label
from .kpis import KPIS_SQL

router = APIRouter(prefix="/reports", tags=["reports"])

MAX_ROWS = 50_000


@router.get("/synopsis.jpg")
async def synopsis_jpg(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
    camera_id: uuid.UUID | None = None,
    hours: int = Query(6, ge=1, le=168),
    max_items: int = Query(48, ge=1, le=96),
    event_type: str | None = None,
):
    """Contact sheet of event snapshots for a time window (video synopsis lite)."""
    from datetime import UTC, datetime, timedelta

    from fastapi.responses import Response

    since = datetime.now(UTC) - timedelta(hours=hours)
    query = (
        select(AnalyticsEvent)
        .where(AnalyticsEvent.timestamp >= since, AnalyticsEvent.snapshot_key.is_not(None))
        .order_by(AnalyticsEvent.timestamp.desc())
        .limit(max_items)
    )
    if camera_id:
        query = query.where(AnalyticsEvent.camera_id == camera_id)
    if event_type:
        query = query.where(AnalyticsEvent.event_type == event_type)
    result = await session.execute(query)
    rows = list(result.scalars().all())

    storage = get_storage()
    items: list[tuple[bytes, str]] = []
    for row in reversed(rows):  # chronological
        if not row.snapshot_key:
            continue
        data = await storage.download_bytes(row.snapshot_key)
        if data:
            items.append((data, fmt_label(row.timestamp, row.event_type)))
    sheet = build_contact_sheet(items)
    return Response(
        content=sheet,
        media_type="image/jpeg",
        headers={"Content-Disposition": 'inline; filename="synopsis.jpg"'},
    )


@router.get("/events.csv")
async def events_csv(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
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
    _: User = Depends(get_current_user),
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


@router.get("/dataset-coco.zip")
async def dataset_coco_zip(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
    camera_id: uuid.UUID | None = None,
    feedback: str | None = None,
    limit: int = Query(500, le=2000),
):
    """TAO-compatible COCO dataset from reviewed event evidence.

    False positives are retained as hard-negative images without annotations.
    """
    from ..dataset import CATEGORIES, CocoImage, build_coco_dataset_zip

    query = (
        select(AnalyticsEvent)
        .where(AnalyticsEvent.snapshot_key.is_not(None))
        .order_by(AnalyticsEvent.timestamp.desc())
        .limit(limit)
    )
    if camera_id:
        query = query.where(AnalyticsEvent.camera_id == camera_id)
    if feedback:
        query = query.where(AnalyticsEvent.feedback == feedback)
    else:
        query = query.where(AnalyticsEvent.feedback.is_not(None))
    rows = list((await session.execute(query)).scalars().all())

    storage = get_storage()
    items: list[CocoImage] = []
    for row in rows:
        snapshot_key = row.snapshot_key
        if not snapshot_key:
            continue
        data = await storage.download_bytes(snapshot_key)
        if not data:
            continue
        meta = row.extra or {}
        width = int(meta.get("frame_width") or 1280)
        height = int(meta.get("frame_height") or 720)
        annotations: list[tuple[str, list[float]]] = []
        bbox = meta.get("bbox")
        class_name = meta.get("vehicle_class") or ("person" if "posture" in meta else None)
        if row.feedback != "false_positive" and bbox and class_name in CATEGORIES:
            annotations.append((class_name, bbox))
        items.append(CocoImage(data, width, height, annotations))

    content = build_coco_dataset_zip(items)
    return StreamingResponse(
        iter([content]),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="dataset-coco.zip"'},
    )
