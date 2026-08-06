async def test_branding_endpoint(client):
    resp = await client.get("/api/v1/branding")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app_name"] == "TestBrand"
    assert "logo_light_url" in data
    assert data["primary_color"].startswith("#")


async def test_healthz(client):
    assert (await client.get("/healthz")).json() == {"status": "ok"}
