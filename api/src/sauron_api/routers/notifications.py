from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, require_admin
from ..db import get_session
from ..models import NotificationChannel, User

router = APIRouter(prefix="/notifications", tags=["notifications"])

_SECRET_KEYS = {"bot_token", "password"}


class ChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: str = Field(pattern="^(webhook|email|telegram)$")
    config: dict
    min_priority: str = "critical"
    camera_id: uuid.UUID | None = None
    enabled: bool = True


class ChannelUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    min_priority: str | None = None
    camera_id: uuid.UUID | None = None
    enabled: bool | None = None


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
    }


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
    await session.delete(ch)
    await session.commit()


@router.post("/{channel_id}/test")
async def test_channel(
    channel_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_admin),
):
    from ..notifier import _send_email, _send_telegram, _send_webhook

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
    except Exception as e:  # noqa: BLE001 - surface the provider error to the caller
        raise HTTPException(502, f"test notification failed: {e}") from None
    return {"status": "sent"}
