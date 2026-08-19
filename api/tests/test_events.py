import io
import time
import uuid

from PIL import Image

PAYLOAD = {
    "event_type": "WRONG_WAY",
    "camera_id": None,  # filled per test
    "timestamp": 0.0,
    "confidence": 0.93,
    "priority": "critical",
    "rule_id": "wrong-way:lane1",
    "object_id": 42,
    "metadata": {"vehicle_class": "truck", "cosine": -0.91},
}


def _payload(stream: str, **overrides):
    p = dict(PAYLOAD)
    p["camera_id"] = stream
    p["timestamp"] = time.time()
    p.update(overrides)
    return p


async def test_ingest_and_list_events(client):
    stream = f"cam-{uuid.uuid4().hex[:8]}"
    resp = await client.post("/api/v1/events", json=_payload(stream))
    assert resp.status_code == 202

    page = (await client.get("/api/v1/events", params={"event_type": "WRONG_WAY"})).json()
    assert page["total"] >= 1
    item = page["items"][0]
    assert item["event_type"] == "WRONG_WAY"
    assert item["priority"] == "critical"
    assert item["object_id"] == 42
    assert item["metadata"]["vehicle_class"] == "truck"
    assert item["snapshot_url"] is None  # storage disabled in tests

    # camera auto-registered from stream_id
    cams = (await client.get("/api/v1/cameras")).json()
    cam = next(c for c in cams if c["stream_id"] == stream)

    filtered = (await client.get("/api/v1/events", params={"camera_id": cam["id"]})).json()
    assert filtered["total"] == 1

    empty = (
        await client.get(
            "/api/v1/events", params={"camera_id": cam["id"], "event_type": "CONGESTION"}
        )
    ).json()
    assert empty["total"] == 0


async def test_events_pagination(client):
    stream = f"cam-{uuid.uuid4().hex[:8]}"
    for i in range(7):
        await client.post(
            "/api/v1/events",
            json=_payload(stream, event_type="LINE_CROSSING", object_id=i, priority="info"),
        )
    cams = (await client.get("/api/v1/cameras")).json()
    cam_id = next(c["id"] for c in cams if c["stream_id"] == stream)

    page1 = (
        await client.get("/api/v1/events", params={"camera_id": cam_id, "page": 1, "page_size": 5})
    ).json()
    assert page1["total"] == 7
    assert len(page1["items"]) == 5
    page2 = (
        await client.get("/api/v1/events", params={"camera_id": cam_id, "page": 2, "page_size": 5})
    ).json()
    assert len(page2["items"]) == 2


async def test_attach_evidence_updates_existing_event(client, monkeypatch):
    class Storage:
        async def upload_snapshot(self, *_args):
            return "snapshots/test.jpg"

        async def presigned_url(self, key):
            return f"http://storage/{key}" if key else None

    monkeypatch.setattr("sauron_api.routers.events.get_storage", lambda: Storage())
    stream = f"cam-{uuid.uuid4().hex[:8]}"
    event_id = uuid.uuid4()
    response = await client.post("/api/v1/events", json=_payload(stream, event_id=str(event_id)))
    assert response.status_code == 202
    assert response.json()["event_id"] == str(event_id)

    image = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, "JPEG")
    response = await client.post(
        f"/api/v1/events/{event_id}/evidence",
        files={"snapshot": ("snapshot.jpg", image.getvalue(), "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["evidence_status"] == "partial"

    page = (await client.get("/api/v1/events", params={"event_type": "WRONG_WAY"})).json()
    item = next(item for item in page["items"] if item["event_id"] == str(event_id))
    assert item["metadata"]["evidence_status"] == "partial"


async def test_attach_evidence_retries_when_storage_is_unavailable(client):
    stream = f"cam-{uuid.uuid4().hex[:8]}"
    event_id = uuid.uuid4()
    await client.post("/api/v1/events", json=_payload(stream, event_id=str(event_id)))
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, "JPEG")

    response = await client.post(
        f"/api/v1/events/{event_id}/evidence",
        files={"snapshot": ("snapshot.jpg", image.getvalue(), "image/jpeg")},
    )

    assert response.status_code == 503


async def test_attach_evidence_requires_media(client):
    response = await client.post(f"/api/v1/events/{uuid.uuid4()}/evidence")
    assert response.status_code == 422


async def test_kpis_requires_postgres(client):
    resp = await client.get("/api/v1/kpis")
    assert resp.status_code == 501
