from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from .config import get_settings
from .db import get_session_factory
from .models import AnalyticsEvent, NotificationChannel, NotificationDelivery
from .notifier import build_payload, safe_provider_error, send_payload
from .storage import get_storage

log = logging.getLogger(__name__)


async def run_notification_worker() -> None:
    settings = get_settings()
    while True:
        try:
            await dispatch_due_deliveries()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("notification outbox worker failed")
        await asyncio.sleep(settings.notification_worker_seconds)


async def dispatch_due_deliveries(limit: int = 50) -> int:
    now = datetime.now(UTC)
    sent = 0
    async with get_session_factory()() as session:
        query = (
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status.in_(("pending", "retry")),
                NotificationDelivery.next_attempt_at <= now,
            )
            .order_by(NotificationDelivery.next_attempt_at)
            .limit(limit)
        )
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        deliveries = list((await session.execute(query)).scalars().all())
        for delivery in deliveries:
            channel = await session.get(NotificationChannel, delivery.channel_id)
            if channel is None or not channel.enabled:
                delivery.status = "cancelled"
                delivery.last_error = "channel missing or disabled"
                continue
            payload = dict(delivery.payload or {})
            if delivery.event_id:
                event = (
                    await session.execute(
                        select(AnalyticsEvent)
                        .where(AnalyticsEvent.event_id == delivery.event_id)
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if event is not None:
                    payload = build_payload(event, str(payload.get("camera") or ""))
                    storage = get_storage()
                    payload["snapshot_url"] = await storage.presigned_url(event.snapshot_key)
                    payload["clip_url"] = await storage.presigned_url(event.clip_key)
            delivery.attempts += 1
            try:
                await send_payload(channel, payload)
                delivery.status = "sent"
                delivery.delivered_at = datetime.now(UTC)
                delivery.last_error = None
                sent += 1
            except Exception as exc:  # noqa: BLE001 - provider errors are persisted for operators
                delivery.last_error = safe_provider_error(exc, channel.config)
                if delivery.attempts >= channel.max_attempts:
                    delivery.status = "failed"
                else:
                    delivery.status = "retry"
                    delay = get_settings().notification_retry_base_seconds * 2 ** (
                        delivery.attempts - 1
                    )
                    delivery.next_attempt_at = datetime.now(UTC) + timedelta(
                        seconds=min(delay, 3600)
                    )
        await session.commit()
    return sent
