from sqlalchemy import select

from sauron_api.db import get_session_factory
from sauron_api.models import PushSubscription
from sauron_api.notify import send_push_to_all


async def test_push_subscribe_upsert(client):
    payload = {"endpoint": "https://push.example.com/sub/1", "keys": {"p256dh": "a", "auth": "b"}}
    resp = await client.post("/api/v1/push/subscribe", json=payload)
    assert resp.status_code == 201
    # upsert same endpoint
    payload2 = {"endpoint": payload["endpoint"], "keys": {"p256dh": "a2", "auth": "b2"}}
    assert (await client.post("/api/v1/push/subscribe", json=payload2)).status_code == 201

    async with get_session_factory()() as session:
        result = await session.execute(select(PushSubscription))
        subs = result.scalars().all()
        mine = [s for s in subs if s.endpoint == payload["endpoint"]]
        assert len(mine) == 1
        assert mine[0].keys["p256dh"] == "a2"


async def test_unsubscribe(client):
    payload = {"endpoint": "https://push.example.com/sub/2", "keys": {"p256dh": "a", "auth": "b"}}
    await client.post("/api/v1/push/subscribe", json=payload)
    assert (
        await client.request("DELETE", "/api/v1/push/subscribe", json=payload)
    ).status_code == 204


async def test_public_key_404_when_unconfigured(client):
    resp = await client.get("/api/v1/push/public-key")
    assert resp.status_code == 404


async def test_send_push_no_vapid_is_noop():
    async with get_session_factory()() as session:
        assert await send_push_to_all(session, "t", "b") == 0
