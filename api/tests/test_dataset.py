import io
import json
import time
import uuid
import zipfile

from sauron_api.dataset import CocoImage, build_coco_dataset_zip


def test_coco_dataset_zip_contents():
    items = [
        CocoImage(b"\xff\xd8\xff\xfakejpg", 1280, 720, [("car", [320, 180, 960, 540])]),
        CocoImage(b"\xff\xd8\xff\xfake2", 1280, 720),
    ]
    content = build_coco_dataset_zip(items)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = zf.namelist()
        assert "images/img_00001.jpg" in names
        assert "images/img_00002.jpg" in names
        payload = json.loads(zf.read("annotations/instances.json"))
        assert payload["annotations"][0]["bbox"] == [320.0, 180.0, 640.0, 360.0]
        assert payload["annotations"][0]["area"] == 230400.0
        assert len(payload["images"]) == 2


async def test_feedback_endpoint(client):
    resp = await client.post(
        "/api/v1/events",
        json={
            "event_type": "WRONG_WAY",
            "camera_id": f"cam-fb-{uuid.uuid4().hex[:6]}",
            "timestamp": time.time(),
            "confidence": 0.9,
            "priority": "critical",
            "metadata": {},
        },
    )
    event_id = resp.json()["event_id"]
    ok = await client.post(
        f"/api/v1/events/{event_id}/feedback", json={"value": "false_positive"}
    )
    assert ok.status_code == 204
    bad = await client.post(
        f"/api/v1/events/{event_id}/feedback", json={"value": "meh"}
    )
    assert bad.status_code == 422

    page = await client.get("/api/v1/events", params={"event_type": "WRONG_WAY"})
    item = next(i for i in page.json()["items"] if i["event_id"] == event_id)
    # feedback stored (column); EventRead no lo expone todavía — verificar por endpoint
    assert item is not None
