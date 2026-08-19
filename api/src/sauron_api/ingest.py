from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AnalyticsEvent, Camera
from .schemas import EventIngest
from .storage import SnapshotStorage

log = logging.getLogger(__name__)


async def get_or_create_camera(session: AsyncSession, stream_id: str) -> Camera:
    result = await session.execute(select(Camera).where(Camera.stream_id == stream_id))
    camera = result.scalar_one_or_none()
    if camera is None:
        camera = Camera(name=stream_id, stream_id=stream_id)
        session.add(camera)
        await session.flush()
        log.info("auto-registered camera for stream %s", stream_id)
    return camera


async def ingest_event(
    session: AsyncSession, storage: SnapshotStorage, payload: EventIngest
) -> AnalyticsEvent:
    """Persist one event: snapshot to S3, row to the events hypertable."""
    camera = await get_or_create_camera(session, payload.camera_id)
    ts = datetime.fromtimestamp(payload.timestamp, tz=UTC)

    snapshot_key = None
    embedding: list[float] | None = None
    if payload.snapshot_jpeg:
        try:
            jpeg = base64.b64decode(payload.snapshot_jpeg)
        except ValueError:
            jpeg = b""
        if jpeg:
            snapshot_key = await storage.upload_snapshot(camera.id, ts, jpeg)
            from .embeddings import get_embeddings

            embedding = await asyncio.to_thread(get_embeddings().embed_image, jpeg)

    clip_key = None
    if payload.clip_mp4:
        try:
            mp4 = base64.b64decode(payload.clip_mp4)
        except ValueError:
            mp4 = b""
        if mp4:
            clip_key = await storage.upload_clip(camera.id, ts, mp4)

    row = AnalyticsEvent(
        event_id=payload.event_id or uuid.uuid4(),
        timestamp=ts,
        camera_id=camera.id,
        event_type=payload.event_type,
        priority=payload.priority,
        confidence=payload.confidence,
        rule_id=payload.rule_id,
        object_id=payload.object_id,
        vehicle_class=(
            str(payload.metadata["vehicle_class"])
            if payload.metadata.get("vehicle_class")
            else None
        ),
        extra=payload.metadata,
        snapshot_key=snapshot_key,
        clip_key=clip_key,
        embedding=embedding,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row
