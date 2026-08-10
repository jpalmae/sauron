import uuid
from datetime import UTC, datetime

import httpx
import pytest

from sauron_api.db import get_session_factory
from sauron_api.models import AnalyticsEvent, NotificationChannel
from sauron_api.notifier import build_payload, matches, notify_channels


def _event(priority="warning", camera_id=None):
    return AnalyticsEvent(
        timestamp=datetime.now(UTC),
        camera_id=camera_id or uuid.uuid4(),
        event_type="WRONG_WAY",
        priority=priority,
        confidence=0.9,
        rule_id="wrong-way:lane1",
        extra={"vehicle_class": "truck", "plate_text": "ABC123"},
    )


def _capture_client(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url), request.read().decode()))
        return httpx.Response(200, json={"ok": True})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestMatches:
    def test_priority_threshold(self):
        ch = NotificationChannel(
            name="x", type="webhook", config={}, min_priority="critical", enabled=True
        )
        assert not matches(ch, _event("warning"), "cam")
        assert matches(ch, _event("critical"), "cam")

    def test_camera_filter(self):
        cam_a, cam_b = uuid.uuid4(), uuid.uuid4()
        ch = NotificationChannel(
            name="x", type="webhook", config={}, min_priority="info", camera_id=cam_a, enabled=True
        )
        assert matches(ch, _event("info", cam_a), "cam")
        assert not matches(ch, _event("info", cam_b), "cam")

    def test_disabled(self):
        ch = NotificationChannel(
            name="x", type="webhook", config={}, min_priority="info", enabled=False
        )
        assert not matches(ch, _event("critical"), "cam")


class TestPayload:
    def test_build_payload(self):
        p = build_payload(_event("warning"), "cam-01")
        assert p["camera"] == "cam-01"
        assert p["metadata"]["plate_text"] == "ABC123"
        assert p["event_type"] == "WRONG_WAY"


class TestNotify:
    @pytest.fixture(autouse=True)
    async def _clean_channels(self):
        from sqlalchemy import delete

        async with get_session_factory()() as session:
            await session.execute(delete(NotificationChannel))
            await session.commit()

    async def test_webhook_fanout(self):
        calls = []
        async with get_session_factory()() as session:
            session.add(
                NotificationChannel(
                    name="ops",
                    type="webhook",
                    config={"url": "https://hooks.example.com/sauron"},
                    min_priority="info",
                    enabled=True,
                )
            )
            await session.commit()
            sent = await notify_channels(session, _event("info"), "cam-01", _capture_client(calls))
            assert sent == 1
        assert len(calls) == 1
        assert calls[0][1] == "https://hooks.example.com/sauron"
        assert "WRONG_WAY" in calls[0][2]

    async def test_telegram_payload(self):
        calls = []
        async with get_session_factory()() as session:
            session.add(
                NotificationChannel(
                    name="tg",
                    type="telegram",
                    config={"bot_token": "T0K3N", "chat_id": "123"},
                    min_priority="info",
                    enabled=True,
                )
            )
            await session.commit()
            sent = await notify_channels(session, _event("critical"), "cam-02", _capture_client(calls))
            assert sent == 1
        assert "api.telegram.org/botT0K3N/sendMessage" in calls[0][1]
        assert "chat_id" in calls[0][2] and '"123"' in calls[0][2]
        assert "WRONG_WAY" in calls[0][2]

    async def test_channel_failure_is_isolated(self):
        def failing_handler(request):
            if "fail" in str(request.url):
                return httpx.Response(500)
            return httpx.Response(200, json={"ok": True})

        client = httpx.AsyncClient(transport=httpx.MockTransport(failing_handler))
        async with get_session_factory()() as session:
            session.add(NotificationChannel(
                name="bad", type="webhook", config={"url": "https://fail.example.com"},
                min_priority="info", enabled=True))
            session.add(NotificationChannel(
                name="good", type="webhook", config={"url": "https://ok.example.com"},
                min_priority="info", enabled=True))
            await session.commit()
            sent = await notify_channels(session, _event("warning"), "cam", client)
            assert sent == 1  # the good one still goes out
