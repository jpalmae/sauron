from __future__ import annotations

import asyncio
import json
import logging

from .ingest import ingest_event
from .metrics import metrics
from .schemas import EventIngest

log = logging.getLogger(__name__)


async def run_consumer(app) -> None:
    """Subscribe to the Redis events channel; persist + broadcast each event.

    Reconnects forever with backoff; cancelled cleanly on shutdown.
    """
    import redis.asyncio as aioredis

    from .db import get_session_factory
    from .storage import get_storage
    from .ws import manager

    settings = app.state.settings
    delay = 1.0
    while True:
        try:
            client = aioredis.from_url(settings.redis_url)
            pubsub = client.pubsub()
            await pubsub.subscribe(settings.redis_events_channel)
            log.info("subscribed to %s", settings.redis_events_channel)
            delay = 1.0
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    payload = EventIngest.model_validate(json.loads(message["data"]))
                except Exception:
                    log.warning("discarding malformed event payload", exc_info=True)
                    continue
                async with get_session_factory()() as session:
                    row = await ingest_event(session, get_storage(), payload)
                metrics.events_ingested += 1
                metrics.ws_broadcasts += 1
                await manager.broadcast(
                    {
                        "event_id": str(row.event_id),
                        "event_type": row.event_type,
                        "priority": row.priority,
                        "camera_id": str(row.camera_id),
                        "timestamp": row.timestamp.isoformat(),
                        "confidence": row.confidence,
                        "rule_id": row.rule_id,
                        "object_id": row.object_id,
                        "metadata": row.extra,
                        "snapshot_key": row.snapshot_key,
                        "clip_key": row.clip_key,
                    }
                )
                if row.priority in ("critical", "warning"):
                    from .notify import send_push_to_all

                    await send_push_to_all(
                        session,
                        title=f"⚠ {row.event_type}",
                        body=f"{row.rule_id} · {payload.camera_id}",
                        url="/",
                    )
                from .notifier import notify_channels

                await notify_channels(session, row, payload.camera_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("events consumer crashed; reconnecting in %.1fs", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)
