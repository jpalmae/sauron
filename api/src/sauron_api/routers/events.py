from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..ingest import ingest_event
from ..models import AnalyticsEvent
from ..schemas import EventIngest, EventPage, EventRead
from ..storage import get_storage

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", status_code=202)
async def post_event(payload: EventIngest, session: AsyncSession = Depends(get_session)):
    """Direct ingest path (alternative to the Redis consumer)."""
    row = await ingest_event(session, get_storage(), payload)
    return {"event_id": str(row.event_id)}


@router.get("", response_model=EventPage)
async def list_events(
    session: AsyncSession = Depends(get_session),
    camera_id: uuid.UUID | None = None,
    event_type: str | None = None,
    priority: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
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
        )
        items.append(item)
    return EventPage(total=total, page=page, page_size=page_size, items=items)
