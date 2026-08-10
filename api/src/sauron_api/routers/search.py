from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..db import get_session
from ..embeddings import cosine, get_embeddings
from ..models import AnalyticsEvent, User
from ..schemas import EventRead
from ..storage import get_storage

router = APIRouter(prefix="/search", tags=["search"])

_PG_SQL = text(
    """
    SELECT event_id, timestamp, camera_id, event_type, priority, confidence,
           rule_id, object_id, snapshot_key, clip_key, metadata,
           acknowledged_at, acknowledged_by,
           embedding <=> (:vec)::vector AS distance
    FROM analytics_events
    WHERE embedding IS NOT NULL
      AND ((:camera_id)::uuid IS NULL OR camera_id = (:camera_id)::uuid)
    ORDER BY embedding <=> (:vec)::vector
    LIMIT :limit
    """
)


@router.get("")
async def semantic_search(
    q: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
    camera_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
):
    """Natural-language evidence search (CLIP embeddings over event snapshots)."""
    emb = get_embeddings()
    vec = await asyncio.to_thread(emb.embed_text, q)
    if vec is None:
        raise HTTPException(503, "semantic search unavailable (CLIP models not loaded)")

    dialect = session.bind.dialect.name if session.bind else ""
    storage = get_storage()
    rows_out: list[tuple[dict, float]] = []

    if dialect == "postgresql":
        rows = (
            await session.execute(
                _PG_SQL, {"vec": str(vec), "camera_id": camera_id, "limit": limit}
            )
        ).mappings()
        for row in rows:
            row_dict: dict = dict(row)  # type: ignore[assignment]
            rows_out.append((row_dict, float(row_dict["distance"])))
    else:
        result = await session.execute(
            select(AnalyticsEvent).where(AnalyticsEvent.embedding.is_not(None)).limit(2000)
        )
        scored = []
        for r in result.scalars().all():
            if not r.embedding:  # JSON-null slips past SQL IS NOT NULL on sqlite
                continue
            scored.append((
                {
                    "event_id": r.event_id,
                    "timestamp": r.timestamp,
                    "camera_id": r.camera_id,
                    "event_type": r.event_type,
                    "priority": r.priority,
                    "confidence": r.confidence,
                    "rule_id": r.rule_id,
                    "object_id": r.object_id,
                    "snapshot_key": r.snapshot_key,
                    "clip_key": r.clip_key,
                    "metadata": r.extra,
                    "acknowledged_at": r.acknowledged_at,
                    "acknowledged_by": r.acknowledged_by,
                },
                1 - cosine(vec, r.embedding),
            ))
        scored.sort(key=lambda x: x[1])
        rows_out = scored[:limit]

    results = []
    for row_dict2, distance in rows_out:
        results.append(
            {
                "distance": round(distance, 4),
                "event": EventRead(
                    event_id=row_dict2["event_id"],
                    timestamp=row_dict2["timestamp"],
                    camera_id=row_dict2["camera_id"],
                    event_type=row_dict2["event_type"],
                    priority=row_dict2["priority"],
                    confidence=row_dict2["confidence"],
                    rule_id=row_dict2["rule_id"],
                    object_id=row_dict2["object_id"],
                    metadata=row_dict2["metadata"],
                    snapshot_url=await storage.presigned_url(row_dict2["snapshot_key"]),
                    clip_url=await storage.presigned_url(row_dict2["clip_key"]),
                    acknowledged_at=row_dict2["acknowledged_at"],
                    acknowledged_by=row_dict2["acknowledged_by"],
                ),
            }
        )
    return {"query": q, "results": results}
