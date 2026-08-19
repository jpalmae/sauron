from __future__ import annotations

import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_admin
from ..db import get_session
from ..models import NotificationChannel, NotificationDelivery, ReportSchedule, User

router = APIRouter(prefix="/notifications", tags=["notifications"])

_SECRET_KEYS = {"bot_token", "headers", "password", "url"}


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(pattern="^(webhook|email|telegram)$")
    config: dict
    min_priority: str = "critical"
    camera_id: uuid.UUID | None = None
    enabled: bool = True
    cooldown_seconds: int = Field(default=60, ge=0, le=86400)
    max_attempts: int = Field(default=5, ge=1, le=20)


class ChannelUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    min_priority: str | None = None
    camera_id: uuid.UUID | None = None
    enabled: bool | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)
    max_attempts: int | None = Field(default=None, ge=1, le=20)


def _read(ch: NotificationChannel) -> dict:
    cfg = {k: ("***" if k in _SECRET_KEYS and v else v) for k, v in ch.config.items()}
    return {
        "id": str(ch.id),
        "name": ch.name,
        "type": ch.type,
        "config": cfg,
        "min_priority": ch.min_priority,
        "camera_id": str(ch.camera_id) if ch.camera_id else None,
        "enabled": ch.enabled,
        "cooldown_seconds": ch.cooldown_seconds,
        "max_attempts": ch.max_attempts,
    }


def _validate_config(channel_type: str, config: dict) -> None:
    if channel_type == "webhook":
        parsed = urlparse(str(config.get("url", "")))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(422, "webhook config requires a valid http(s) URL")
    elif channel_type == "telegram":
        if not config.get("bot_token") or not config.get("chat_id"):
            raise HTTPException(422, "telegram config requires bot_token and chat_id")
    elif channel_type == "email":
        required = ("smtp_host", "to_addrs")
        if any(not config.get(key) for key in required) or not (
            config.get("username") or config.get("from_addr")
        ):
            raise HTTPException(
                422, "email config requires smtp_host, to_addrs and username or from_addr"
            )
        try:
            port = int(config.get("smtp_port", 587))
        except (TypeError, ValueError):
            raise HTTPException(422, "smtp_port must be an integer") from None
        if not 1 <= port <= 65535:
            raise HTTPException(422, "smtp_port must be between 1 and 65535")


@router.get("")
async def list_channels(
    session: AsyncSession = Depends(get_session), _: User = Depends(get_current_user)
):
    result = await session.execute(select(NotificationChannel).order_by(NotificationChannel.name))
    return [_read(ch) for ch in result.scalars().all()]


@router.post("", status_code=201)
async def create_channel(
    payload: ChannelCreate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    _validate_config(payload.type, payload.config)
    ch = NotificationChannel(**payload.model_dump())
    session.add(ch)
    await session.commit()
    await session.refresh(ch)
    return _read(ch)


@router.patch("/{channel_id}")
async def update_channel(
    channel_id: uuid.UUID,
    payload: ChannelUpdate,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    ch = await session.get(NotificationChannel, channel_id)
    if ch is None:
        raise HTTPException(404, "channel not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "config":
            # keep secrets when masked
            merged = dict(ch.config)
            for k, v in value.items():
                if k in _SECRET_KEYS and v == "***":
                    continue
                merged[k] = v
            _validate_config(ch.type, merged)
            ch.config = merged
        else:
            setattr(ch, field, value)
    await session.commit()
    await session.refresh(ch)
    return _read(ch)


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    ch = await session.get(NotificationChannel, channel_id)
    if ch is None:
        raise HTTPException(404, "channel not found")
    await session.execute(
        delete(NotificationDelivery).where(NotificationDelivery.channel_id == channel_id)
    )
    await session.execute(delete(ReportSchedule).where(ReportSchedule.channel_id == channel_id))
    await session.delete(ch)
    await session.commit()


@router.post("/{channel_id}/test")
async def test_channel(
    channel_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    from ..notifier import _send_email, _send_telegram, _send_webhook, safe_provider_error

    ch = await session.get(NotificationChannel, channel_id)
    if ch is None:
        raise HTTPException(404, "channel not found")
    payload: dict = {
        "event_id": "test",
        "event_type": "TEST",
        "priority": "info",
        "camera": "test",
        "timestamp": "2026-01-01T00:00:00Z",
        "rule_id": "test",
        "metadata": {},
        "snapshot_key": None,
    }
    try:
        if ch.type == "webhook":
            await _send_webhook(ch.config, payload, None)
        elif ch.type == "telegram":
            await _send_telegram(ch.config, payload, None)
        elif ch.type == "email":
            await _send_email(ch.config, payload)
    except Exception as e:  # noqa: BLE001 - surface a sanitized provider error to the caller
        raise HTTPException(502, f"test notification failed: {safe_provider_error(e, ch.config)}") from None
    return {"status": "sent"}
