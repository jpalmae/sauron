import csv
import io
import time
import uuid


async def test_events_csv_export(client):
    stream = f"cam-{uuid.uuid4().hex[:8]}"
    await client.post(
        "/api/v1/events",
        json={
            "event_type": "LINE_CROSSING",
            "camera_id": stream,
            "timestamp": time.time(),
            "confidence": 0.88,
            "priority": "info",
            "rule_id": "L1",
            "object_id": 5,
            "metadata": {"vehicle_class": "bus", "speed_kmh": 42.5},
        },
    )
    resp = await client.get("/api/v1/reports/events.csv", params={"event_type": "LINE_CROSSING"})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment" in resp.headers["content-disposition"]

    rows = list(csv.DictReader(io.StringIO(resp.text)))
    match = [r for r in rows if r["camera"] == stream]
    assert len(match) == 1
    assert match[0]["vehicle_class"] == "bus"
    assert match[0]["speed_kmh"] == "42.5"
    assert match[0]["event_type"] == "LINE_CROSSING"


async def test_events_csv_filters_priority(client):
    resp = await client.get("/api/v1/reports/events.csv", params={"priority": "no-such-priority"})
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert rows == []


async def test_kpis_csv_requires_postgres(client):
    resp = await client.get("/api/v1/reports/kpis.csv")
    assert resp.status_code == 501
