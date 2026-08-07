import time
import uuid

from sauron_api.auth import create_token, hash_password
from sauron_api.db import get_session_factory
from sauron_api.models import User

from .test_auth import TEST_SETTINGS
from .test_auth import auth_on as _auth_on  # fixture

auth_on = _auth_on


async def test_ack_flow(client, auth_on):
    # ingest via ingest token
    payload = {
        "event_type": "STOPPED_VEHICLE",
        "camera_id": f"cam-{uuid.uuid4().hex[:8]}",
        "timestamp": time.time(),
        "confidence": 0.9,
        "priority": "warning",
        "metadata": {"vehicle_class": "car"},
    }
    headers_ingest = {"Authorization": f"Bearer {TEST_SETTINGS.ingest_token}"}
    resp = await client.post("/api/v1/events", json=payload, headers=headers_ingest)
    assert resp.status_code == 202
    event_id = resp.json()["event_id"]

    async with get_session_factory()() as session:
        user = User(email="op2@sauron.dev", role="viewer", hashed_password=hash_password("pw"))
        session.add(user)
        await session.commit()
        await session.refresh(user)
        token = create_token(user)

    headers = {"Authorization": f"Bearer {token}"}
    acked = await client.post(f"/api/v1/events/{event_id}/ack", headers=headers)
    assert acked.status_code == 200
    assert acked.json()["acknowledged_by"] == "op2@sauron.dev"
    assert acked.json()["acknowledged_at"] is not None

    # idempotent: second ack keeps the original timestamp/by
    again = await client.post(f"/api/v1/events/{event_id}/ack", headers=headers)
    assert again.json()["acknowledged_at"] == acked.json()["acknowledged_at"]

    # pending_only excludes acknowledged events
    pending = await client.get(
        "/api/v1/events", params={"pending_only": "true", "priority": "warning"}, headers=headers
    )
    assert all(e["event_id"] != event_id for e in pending.json()["items"])

    # unknown id -> 404
    missing = await client.post(f"/api/v1/events/{uuid.uuid4()}/ack", headers=headers)
    assert missing.status_code == 404
