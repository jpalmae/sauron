import uuid

import pytest

from sauron_api.camera_probe import ProbeResult, parse_onvif_response, probe_camera


def test_parse_onvif_probe_response():
    payload = b"""<?xml version="1.0"?>
    <e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
      xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
      xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing">
      <e:Body><d:ProbeMatches><d:ProbeMatch>
        <a:EndpointReference><a:Address>urn:uuid:camera-1</a:Address></a:EndpointReference>
        <d:Scopes>onvif://www.onvif.org/name/Entrada_Norte onvif://www.onvif.org/location/Bodega</d:Scopes>
        <d:XAddrs>http://192.0.2.10/onvif/device_service</d:XAddrs>
      </d:ProbeMatch></d:ProbeMatches></e:Body>
    </e:Envelope>"""

    devices = parse_onvif_response(payload, "192.0.2.10")

    assert devices == [
        {
            "endpoint": "urn:uuid:camera-1",
            "ip": "192.0.2.10",
            "xaddrs": ["http://192.0.2.10/onvif/device_service"],
            "scopes": [
                "onvif://www.onvif.org/name/Entrada_Norte",
                "onvif://www.onvif.org/location/Bodega",
            ],
            "name": "Entrada Norte",
            "location": "Bodega",
        }
    ]


def test_probe_rejects_non_camera_scheme():
    with pytest.raises(ValueError, match="camera URL"):
        probe_camera("file:///tmp/video.mp4")


async def test_probe_saved_camera_persists_diagnostics(client, monkeypatch):
    stream_id = f"probe-{uuid.uuid4().hex[:8]}"
    created = (
        await client.post(
            "/api/v1/cameras",
            json={
                "name": "Probe camera",
                "stream_id": stream_id,
                "rtsp_url": "rtsp://camera.example/live",
            },
        )
    ).json()
    result = ProbeResult("ok", 123, "h264", 1920, 1080, 25.0, "yuv420p", 4000, "an-image", None)
    monkeypatch.setattr("sauron_api.routers.cameras.probe_camera", lambda *_args: result)

    response = await client.post(f"/api/v1/cameras/{created['id']}/probe")

    assert response.status_code == 200
    assert response.json()["width"] == 1920
    camera = (await client.get(f"/api/v1/cameras/{created['id']}")).json()
    assert camera["probe_status"] == "ok"
    assert camera["probe_details"]["codec"] == "h264"
    assert "preview_jpeg" not in camera["probe_details"]
