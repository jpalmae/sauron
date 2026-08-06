import base64
import json
import sys
import types

import httpx
import numpy as np

from sauron_inference.bridge.common import event_payload
from sauron_inference.bridge.http_publisher import HTTPEventPublisher
from sauron_inference.rules.events import Event, EventType, Priority


def make_event(with_snapshot: bool) -> Event:
    return Event(
        event_type=EventType.WRONG_WAY,
        camera_id="cam-01",
        timestamp=1786000000.0,
        confidence=0.92,
        priority=Priority.CRITICAL,
        rule_id="wrong-way:lane1",
        object_id=7,
        metadata={"vehicle_class": "car"},
        snapshot=np.zeros((64, 64, 3), dtype=np.uint8) if with_snapshot else None,
    )


def test_event_payload_with_snapshot():
    p = event_payload(make_event(True))
    assert p["event_type"] == "WRONG_WAY"
    assert p["has_snapshot"] is True
    jpeg = base64.b64decode(p["snapshot_jpeg"])
    assert jpeg[:2] == b"\xff\xd8"  # JPEG magic
    assert p["metadata"]["vehicle_class"] == "car"


def test_event_payload_without_snapshot():
    p = event_payload(make_event(False))
    assert "snapshot_jpeg" not in p
    assert p["has_snapshot"] is False
    json.dumps(p)  # must be JSON-serializable


def test_redis_publisher(monkeypatch):
    published = []

    class FakeRedis:
        @classmethod
        def from_url(cls, url):
            assert url == "redis://example:6379/0"
            return cls()

        def publish(self, channel, data):
            published.append((channel, data))

    fake_module = types.ModuleType("redis")
    fake_module.Redis = FakeRedis
    monkeypatch.setitem(sys.modules, "redis", fake_module)

    from sauron_inference.bridge.redis_publisher import RedisEventPublisher

    pub = RedisEventPublisher("redis://example:6379/0", channel="test:events")
    pub(make_event(True))

    assert len(published) == 1
    channel, data = published[0]
    assert channel == "test:events"
    parsed = json.loads(data)
    assert parsed["event_type"] == "WRONG_WAY"
    assert parsed["snapshot_jpeg"]


def test_http_publisher():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(202, json={"event_id": "abc"})

    client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://api:8000"
    )
    pub = HTTPEventPublisher("http://api:8000", client=client)
    pub(make_event(False))

    assert captured["path"] == "/api/v1/events"
    assert captured["body"]["priority"] == "critical"
    assert captured["body"]["object_id"] == 7
