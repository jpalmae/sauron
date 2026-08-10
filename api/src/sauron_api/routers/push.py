from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import get_settings
from ..db import get_session
from ..models import PushSubscription, User

router = APIRouter(prefix="/push", tags=["push"])


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: dict  # {p256dh, auth}


@router.get("/public-key")
async def public_key(_: User = Depends(get_current_user)):
    key = get_settings().vapid_public_key
    if not key:
        raise HTTPException(404, "web push not configured (VAPID keys missing)")
    return {"public_key": key}


@router.post("/subscribe", status_code=201)
async def subscribe(
    payload: SubscribeRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        sub = PushSubscription(
            endpoint=payload.endpoint, keys=payload.keys, user_email=user.email
        )
        session.add(sub)
    else:
        sub.keys = payload.keys
        sub.user_email = user.email
    await session.commit()
    return {"status": "subscribed"}


@router.delete("/subscribe", status_code=204)
async def unsubscribe(
    payload: SubscribeRequest,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    await session.execute(
        delete(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    await session.commit()
