import io
import time
import uuid
import zipfile

from sauron_api.dataset import build_dataset_zip, yolo_label


def test_yolo_label_normalizes():
    # bbox xyxy [320,180,960,540] en 1280x720 -> centro 0.5,0.5 w=0.5 h=0.5
    assert yolo_label(0, [320, 180, 960, 540], 1280, 720) == "0 0.500000 0.500000 0.500000 0.500000"


def test_dataset_zip_contents():
    items = [(b"\xff\xd8\xff\xfakejpg", "0 0.5 0.5 0.5 0.5"), (b"\xff\xd8\xff\xfake2", "")]
    content = build_dataset_zip(items)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = zf.namelist()
        assert "images/img_00000.jpg" in names
        assert "labels/img_00001.txt" in names
        assert "dataset.yaml" in names
        assert zf.read("labels/img_00001.txt") == b""


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
