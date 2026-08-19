import uuid


async def test_camera_crud(client):
    stream = f"cam-{uuid.uuid4().hex[:8]}"
    created = await client.post(
        "/api/v1/cameras",
        json={
            "name": "Entrada Norte",
            "stream_id": stream,
            "rtsp_url": "rtsp://cam/1",
            "roi_config": {"lines": [{"id": "L1", "points": [[0, 1], [2, 3]]}]},
        },
    )
    assert created.status_code == 201
    cam = created.json()
    assert cam["roi_config"]["lines"][0]["id"] == "L1"
    assert cam["is_active"] is True

    dup = await client.post(
        "/api/v1/cameras", json={"name": "x", "stream_id": stream}
    )
    assert dup.status_code == 409

    got = await client.get(f"/api/v1/cameras/{cam['id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "Entrada Norte"

    updated_stream = f"cam-{uuid.uuid4().hex[:8]}"
    patched = await client.patch(
        f"/api/v1/cameras/{cam['id']}",
        json={"is_active": False, "name": "Salida", "stream_id": updated_stream},
    )
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False
    assert patched.json()["name"] == "Salida"
    assert patched.json()["stream_id"] == updated_stream

    listed = await client.get("/api/v1/cameras")
    assert listed.status_code == 200
    assert any(c["stream_id"] == updated_stream for c in listed.json())

    deleted = await client.delete(f"/api/v1/cameras/{cam['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/cameras/{cam['id']}")).status_code == 404


async def test_camera_not_found(client):
    assert (await client.get(f"/api/v1/cameras/{uuid.uuid4()}")).status_code == 404
