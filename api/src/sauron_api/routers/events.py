from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_ingest
from ..db import get_session
from ..ingest import ingest_event
from ..models import AnalyticsEvent, User
from ..schemas import EventIngest, EventPage, EventRead
from ..storage import get_storage

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", status_code=202)
async def post_event(
    payload: EventIngest,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_ingest),
):
    """Direct ingest path (alternative to the Redis consumer)."""
    row = await ingest_event(session, get_storage(), payload)
    return {"event_id": str(row.event_id)}


@router.get("", response_model=EventPage)
async def list_events(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
    camera_id: uuid.UUID | None = None,
    event_type: str | None = None,
    priority: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    pending_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    query = select(AnalyticsEvent)
    count_query = select(func.count()).select_from(AnalyticsEvent)
    filters = []
    if camera_id:
        filters.append(AnalyticsEvent.camera_id == camera_id)
    if event_type:
        filters.append(AnalyticsEvent.event_type == event_type)
    if priority:
        filters.append(AnalyticsEvent.priority == priority)
    if since:
        filters.append(AnalyticsEvent.timestamp >= since)
    if until:
        filters.append(AnalyticsEvent.timestamp <= until)
    if pending_only:
        filters.append(AnalyticsEvent.acknowledged_at.is_(None))
    for f in filters:
        query = query.where(f)
        count_query = count_query.where(f)

    total = (await session.execute(count_query)).scalar_one()
    result = await session.execute(
        query.order_by(AnalyticsEvent.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    storage = get_storage()
    items: list[EventRead] = []
    for row in result.scalars().all():
        item = EventRead(
            event_id=row.event_id,
            timestamp=row.timestamp,
            camera_id=row.camera_id,
            event_type=row.event_type,
            priority=row.priority,
            confidence=row.confidence,
            rule_id=row.rule_id,
            object_id=row.object_id,
            metadata=row.extra,
            snapshot_url=await storage.presigned_url(row.snapshot_key),
            clip_url=await storage.presigned_url(row.clip_key),
            acknowledged_at=row.acknowledged_at,
            acknowledged_by=row.acknowledged_by,
        )
        items.append(item)
    return EventPage(total=total, page=page, page_size=page_size, items=items)


@router.post("/{event_id}/ack", response_model=EventRead)
async def ack_event(
    event_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Acknowledge an alert (acuse de recibo)."""
    result = await session.execute(
        select(AnalyticsEvent).where(AnalyticsEvent.event_id == event_id).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "event not found")
    if row.acknowledged_at is None:
        row.acknowledged_at = datetime.now(UTC)
        row.acknowledged_by = user.email
        await session.commit()
        await session.refresh(row)
    storage = get_storage()
    return EventRead(
        event_id=row.event_id,
        timestamp=row.timestamp,
        camera_id=row.camera_id,
        event_type=row.event_type,
        priority=row.priority,
        confidence=row.confidence,
        rule_id=row.rule_id,
        object_id=row.object_id,
        metadata=row.extra,
        snapshot_url=await storage.presigned_url(row.snapshot_key),
        clip_url=await storage.presigned_url(row.clip_key),
        acknowledged_at=row.acknowledged_at,
        acknowledged_by=row.acknowledged_by,
    )
