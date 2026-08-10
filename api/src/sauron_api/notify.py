from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import PushSubscription

log = logging.getLogger(__name__)


async def send_push_to_all(session: AsyncSession, title: str, body: str, url: str = "/") -> int:
    """Send a Web Push notification to every subscription. Returns delivered count."""
    settings = get_settings()
    if not settings.vapid_private_key or not settings.vapid_public_key:
        return 0
    result = await session.execute(select(PushSubscription))
    subs = result.scalars().all()
    if not subs:
        return 0

    payload = json.dumps({"title": title, "body": body, "url": url})
    delivered = 0
    dead: list[str] = []
    for sub in subs:
        ok = await asyncio.to_thread(
            _send_one, sub.endpoint, sub.keys, payload, settings.vapid_private_key,
            settings.vapid_contact,
        )
        if ok:
            delivered += 1
        elif ok is False:
            dead.append(sub.endpoint)
    if dead:
        await session.execute(
            delete(PushSubscription).where(PushSubscription.endpoint.in_(dead))
        )
        await session.commit()
    return delivered


def _send_one(endpoint: str, keys: dict, payload: str, private_key: str, contact: str) -> bool | None:
    """True=delivered, False=subscription dead (410/404), None=transient error."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={"endpoint": endpoint, "keys": keys},
            data=payload,
            vapid_private_key=private_key,
            vapid_claims={"sub": contact},
        )
        return True
    except WebPushException as e:
        status = e.response.status_code if e.response is not None else 0
        if status in (404, 410):
            log.info("push subscription dead, dropping %s", endpoint[:60])
            return False
        log.warning("push failed (%s): %s", status, e)
        return None
