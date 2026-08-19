from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import AnalyticsEvent, NotificationChannel, NotificationDelivery

log = logging.getLogger(__name__)

_PRIORITY_RANK = {"info": 0, "warning": 1, "critical": 2}


def safe_provider_error(error: Exception, config: dict) -> str:
    """Return an operator-useful provider error without persisting channel secrets."""
    message = str(error)
    for key in ("url", "bot_token", "password"):
        value = config.get(key)
        if value:
            message = message.replace(str(value), f"<redacted-{key.replace('_', '-')}>")
    headers = config.get("headers")
    if isinstance(headers, dict):
        for value in headers.values():
            if value:
                message = message.replace(str(value), "<redacted-header>")
    return message[:1000] or type(error).__name__


def matches(channel: NotificationChannel, event: AnalyticsEvent, camera_stream: str) -> bool:
    if not channel.enabled:
        return False
    if _PRIORITY_RANK.get(event.priority, 0) < _PRIORITY_RANK.get(channel.min_priority, 2):
        return False
    return not (channel.camera_id is not None and channel.camera_id != event.camera_id)


def build_payload(event: AnalyticsEvent, camera_stream: str) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "event_type": event.event_type,
        "priority": event.priority,
        "camera": camera_stream,
        "timestamp": event.timestamp.isoformat(),
        "rule_id": event.rule_id,
        "metadata": event.extra or {},
        "snapshot_key": event.snapshot_key,
    }


async def notify_channels(
    session: AsyncSession,
    event: AnalyticsEvent,
    camera_stream: str,
    client: httpx.AsyncClient | None = None,
) -> int:
    """Queue matching channels durably; an injected client keeps unit/direct mode synchronous."""
    result = await session.execute(
        select(NotificationChannel).where(NotificationChannel.enabled.is_(True))
    )
    channels = result.scalars().all()
    payload = build_payload(event, camera_stream)
    sent = 0
    for ch in channels:
        if not matches(ch, event, camera_stream):
            continue
        try:
            if client is not None:
                await send_payload(ch, payload, client)
            else:
                cooldown = max(0, ch.cooldown_seconds)
                bucket = int(event.timestamp.timestamp()) // cooldown if cooldown else 0
                dedupe_key = (
                    f"event:{event.camera_id}:{event.event_type}:{event.rule_id}:{bucket}"
                    if cooldown
                    else f"event:{event.event_id}"
                )
                delivery = NotificationDelivery(
                    channel_id=ch.id,
                    event_id=event.event_id,
                    dedupe_key=dedupe_key,
                    status="pending",
                    next_attempt_at=datetime.now(UTC)
                    + timedelta(seconds=get_settings().notification_evidence_grace_seconds),
                    payload=payload,
                )
                try:
                    async with session.begin_nested():
                        session.add(delivery)
                        await session.flush()
                except IntegrityError:
                    log.info("notification suppressed by cooldown: %s", dedupe_key)
                    continue
            sent += 1
        except Exception:
            log.exception("notification failed: channel %s (%s)", ch.name, ch.type)
    if client is None:
        await session.commit()
    return sent


async def send_payload(
    channel: NotificationChannel,
    payload: dict,
    client: httpx.AsyncClient | None = None,
) -> None:
    if channel.type == "webhook":
        await _send_webhook(channel.config, payload, client)
    elif channel.type == "telegram":
        await _send_telegram(channel.config, payload, client)
    elif channel.type == "email":
        await _send_email(channel.config, payload)
    else:
        raise ValueError(f"unknown channel type: {channel.type}")


async def _send_webhook(config: dict, payload: dict, client: httpx.AsyncClient | None) -> None:
    url = config["url"]
    headers = config.get("headers", {})
    http = client or httpx.AsyncClient(timeout=10.0)
    close = client is None
    try:
        resp = await http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
    finally:
        if close:
            await http.aclose()


async def _send_telegram(config: dict, payload: dict, client: httpx.AsyncClient | None) -> None:
    token = config["bot_token"]
    chat_id = config["chat_id"]
    meta = payload["metadata"]
    extras = " · ".join(
        f"{k}={v}" for k, v in meta.items() if k in ("vehicle_class", "plate_text", "speed_kmh")
    )
    text = (
        f"⚠️ <b>{payload['event_type']}</b> [{payload['priority']}]\n"
        f"{payload['camera']} · {payload['rule_id']}\n"
        f"{payload['timestamp'][:19]}"
        + (f"\n{extras}" if extras else "")
        + (f"\n📷 {payload['snapshot_url']}" if payload.get("snapshot_url") else "")
        + (f"\n🎬 {payload['clip_url']}" if payload.get("clip_url") else "")
        + (f"\n📊 {payload['report_url']}" if payload.get("report_url") else "")
    )
    http = client or httpx.AsyncClient(timeout=10.0)
    close = client is None
    try:
        resp = await http.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        )
        resp.raise_for_status()
    finally:
        if close:
            await http.aclose()


async def _send_email(config: dict, payload: dict) -> None:
    from email.message import EmailMessage

    import aiosmtplib

    msg = EmailMessage()
    msg["From"] = config.get("from_addr", config["username"])
    msg["To"] = config["to_addrs"]
    msg["Subject"] = f"[Sauron] {payload['event_type']} en {payload['camera']}"
    body = "\n".join(f"{k}: {v}" for k, v in payload.items() if k != "metadata")
    body += "\n" + str(payload["metadata"])
    msg.set_content(body)
    await asyncio.wait_for(
        aiosmtplib.send(
            msg,
            hostname=config["smtp_host"],
            port=config.get("smtp_port", 587),
            username=config.get("username"),
            password=config.get("password"),
            start_tls=config.get("start_tls", True),
            timeout=15,
        ),
        timeout=20,
    )
