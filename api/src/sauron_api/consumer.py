from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .ingest import ingest_event
from .metrics import metrics
from .schemas import EventIngest

log = logging.getLogger(__name__)


async def _process_payload(payload: EventIngest) -> None:
    from .db import get_session_factory
    from .storage import get_storage
    from .ws import manager

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
        if row.event_type == "LINE_CROSSING":
            from .matcher import maybe_create_travel_time

            travel = await maybe_create_travel_time(session, row)
            if travel is not None:
                await manager.broadcast(
                    {
                        "event_id": str(travel.event_id),
                        "event_type": travel.event_type,
                        "priority": travel.priority,
                        "camera_id": str(travel.camera_id),
                        "timestamp": travel.timestamp.isoformat(),
                        "confidence": travel.confidence,
                        "rule_id": travel.rule_id,
                        "object_id": travel.object_id,
                        "metadata": travel.extra,
                        "snapshot_key": None,
                        "clip_key": None,
                    }
                )


def _field(fields: dict[Any, Any], name: str) -> Any:
    return fields.get(name, fields.get(name.encode()))


def _has_messages(batches: list) -> bool:
    """Redis may return ``[[stream, []]]`` instead of an empty list."""
    return any(messages for _stream_name, messages in batches)


async def run_consumer(app) -> None:
    """Reliably persist events from a Redis Stream consumer group.

    A message is acknowledged only after database ingest and downstream
    notifications complete. On restart, this fixed consumer first drains its
    own pending entries and then resumes new entries.
    """
    import redis.asyncio as aioredis
    from redis.exceptions import ResponseError

    settings = app.state.settings
    stream = settings.redis_events_stream
    group = settings.redis_events_group
    consumer = settings.redis_events_consumer
    delay = 1.0
    while True:
        client = None
        try:
            client = aioredis.from_url(settings.redis_url)
            try:
                await client.xgroup_create(stream, group, id="0", mkstream=True)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise
            log.info("consuming Redis stream %s as %s/%s", stream, group, consumer)
            delay = 1.0
            read_id = "0"
            while True:
                batches = await client.xreadgroup(
                    group,
                    consumer,
                    {stream: read_id},
                    count=20,
                    block=1000 if read_id == ">" else None,
                )
                if not _has_messages(batches):
                    read_id = ">"
                    continue
                for _stream_name, messages in batches:
                    for message_id, fields in messages:
                        try:
                            raw = _field(fields, "data")
                            payload = EventIngest.model_validate(json.loads(raw))
                        except Exception:
                            log.warning("discarding malformed event %r", message_id, exc_info=True)
                            await client.xack(stream, group, message_id)
                            continue
                        await _process_payload(payload)
                        await client.xack(stream, group, message_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("events consumer crashed; reconnecting in %.1fs", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)
        finally:
            if client is not None:
                await client.aclose()
