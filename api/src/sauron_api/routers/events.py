from __future__ import annotations

import asyncio
import io
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_ingest
from ..config import get_settings
from ..db import get_session
from ..ingest import ingest_event
from ..models import AnalyticsEvent, User
from ..schemas import EventIngest, EventPage, EventRead
from ..storage import get_storage

router = APIRouter(prefix="/events", tags=["events"])


async def _read_upload(upload: UploadFile | None, limit: int, label: str) -> bytes | None:
    if upload is None:
        return None
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"{label} exceeds {limit} bytes")
    return data or None


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


@router.post("/{event_id}/evidence")
async def attach_evidence(
    event_id: uuid.UUID,
    snapshot: UploadFile | None = File(default=None),
    clip: UploadFile | None = File(default=None),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_ingest),
):
    """Attach asynchronously generated media without delaying the original alert."""
    if snapshot is None and clip is None:
        raise HTTPException(422, "snapshot or clip is required")
    settings = get_settings()
    snapshot_data = await _read_upload(snapshot, settings.evidence_max_snapshot_bytes, "snapshot")
    clip_data = await _read_upload(clip, settings.evidence_max_clip_bytes, "clip")
    if snapshot_data is not None and not snapshot_data.startswith(b"\xff\xd8"):
        raise HTTPException(415, "snapshot must be a JPEG image")
    if snapshot_data is not None:
        try:
            with Image.open(io.BytesIO(snapshot_data)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError):
            raise HTTPException(415, "snapshot must be a valid JPEG image") from None
    if clip_data is not None and b"ftyp" not in clip_data[:32]:
        raise HTTPException(415, "clip must be an MP4 file")
    result = await session.execute(
        select(AnalyticsEvent).where(AnalyticsEvent.event_id == event_id).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "event not found")
    storage = get_storage()
    if snapshot_data is not None:
        snapshot_key = await storage.upload_snapshot(row.camera_id, row.timestamp, snapshot_data)
        if snapshot_key is None:
            raise HTTPException(503, "snapshot storage is unavailable")
        row.snapshot_key = snapshot_key
        from ..embeddings import get_embeddings

        row.embedding = await asyncio.to_thread(get_embeddings().embed_image, snapshot_data)
    if clip_data is not None:
        clip_key = await storage.upload_clip(row.camera_id, row.timestamp, clip_data)
        if clip_key is None:
            raise HTTPException(503, "clip storage is unavailable")
        row.clip_key = clip_key
    metadata = dict(row.extra or {})
    metadata["evidence_status"] = "complete" if row.snapshot_key and row.clip_key else "partial"
    metadata["evidence_updated_at"] = datetime.now(UTC).isoformat()
    row.extra = metadata
    await session.commit()
    snapshot_url = await storage.presigned_url(row.snapshot_key)
    clip_url = await storage.presigned_url(row.clip_key)
    from ..ws import manager

    await manager.broadcast(
        {
            "kind": "evidence_update",
            "event_id": str(row.event_id),
            "snapshot_url": snapshot_url,
            "clip_url": clip_url,
            "metadata": metadata,
        }
    )
    return {
        "event_id": str(row.event_id),
        "evidence_status": metadata["evidence_status"],
        "snapshot_url": snapshot_url,
        "clip_url": clip_url,
    }


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


class FeedbackRequest(BaseModel):
    value: str  # correct | false_positive


@router.post("/{event_id}/feedback", status_code=204)
async def set_feedback(
    event_id: uuid.UUID,
    payload: FeedbackRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Operator verdict on an event (feeds the model improvement loop)."""
    if payload.value not in ("correct", "false_positive"):
        raise HTTPException(422, "value must be 'correct' or 'false_positive'")
    result = await session.execute(
        select(AnalyticsEvent).where(AnalyticsEvent.event_id == event_id).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "event not found")
    row.feedback = payload.value
    await session.commit()
