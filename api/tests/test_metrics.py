async def test_metrics_endpoint(client):
    await client.get("/api/v1/cameras")
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "sauron_api_requests_total" in text
    assert 'path="cameras"' in text
    assert "sauron_api_uptime_seconds" in text


async def test_metrics_route_labels(client):
    await client.get("/api/v1/branding")
    resp = await client.get("/metrics")
    assert 'path="branding"' in resp.text
