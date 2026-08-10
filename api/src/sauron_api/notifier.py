from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AnalyticsEvent, NotificationChannel

log = logging.getLogger(__name__)

_PRIORITY_RANK = {"info": 0, "warning": 1, "critical": 2}


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
    """Fan out an event to all matching notification channels. Returns sent count."""
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
            if ch.type == "webhook":
                await _send_webhook(ch.config, payload, client)
            elif ch.type == "telegram":
                await _send_telegram(ch.config, payload, client)
            elif ch.type == "email":
                await _send_email(ch.config, payload)
            else:
                log.warning("unknown channel type: %s", ch.type)
                continue
            sent += 1
        except Exception:
            log.exception("notification failed: channel %s (%s)", ch.name, ch.type)
    return sent


async def _send_webhook(
    config: dict, payload: dict, client: httpx.AsyncClient | None
) -> None:
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


async def _send_telegram(
    config: dict, payload: dict, client: httpx.AsyncClient | None
) -> None:
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
