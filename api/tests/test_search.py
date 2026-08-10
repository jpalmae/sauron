
import pytest

from sauron_api import embeddings as emb_module
from sauron_api.embeddings import ClipEmbeddings, cosine


def test_cosine():
    assert cosine([1, 0, 0], [1, 0, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([1, 1], [1, 1]) == pytest.approx(1.0)


class FakeEmbeddings(ClipEmbeddings):
    available = True

    def embed_text(self, query):
        return [1.0, 0.0, 0.0] if "camión" in query else [0.0, 1.0, 0.0]

    def embed_image(self, jpeg):
        return [1.0, 0.0, 0.0]


async def test_search_unavailable_returns_503(client, monkeypatch):
    fake = ClipEmbeddings(models_dir="/nonexistent")
    monkeypatch.setattr(emb_module, "_embeddings", fake)
    resp = await client.get("/api/v1/search", params={"q": "camión rojo"})
    assert resp.status_code == 503


async def test_search_ranks_by_similarity(client, monkeypatch):
    import base64
    import time
    import uuid

    monkeypatch.setattr(emb_module, "_embeddings", FakeEmbeddings(models_dir="x"))

    # ingest two events with snapshots; FakeEmbeddings.embed_image gives [1,0,0]
    for i in range(2):
        resp = await client.post(
            "/api/v1/events",
            json={
                "event_type": "LINE_CROSSING",
                "camera_id": f"cam-search-{uuid.uuid4().hex[:6]}",
                "timestamp": time.time(),
                "confidence": 0.9,
                "metadata": {"vehicle_class": "truck"},
                "snapshot_jpeg": base64.b64encode(b"\xff\xd8\xff\xe0fake").decode(),
            },
        )
        assert resp.status_code == 202

    resp = await client.get("/api/v1/search", params={"q": "camión rojo"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "camión rojo"
    assert len(data["results"]) >= 2
    assert data["results"][0]["distance"] == pytest.approx(0.0, abs=1e-3)
    assert data["results"][0]["event"]["metadata"]["vehicle_class"] == "truck"
