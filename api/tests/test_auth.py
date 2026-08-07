import pytest

from sauron_api import config
from sauron_api.auth import create_token, decode_token, hash_password
from sauron_api.config import Settings
from sauron_api.db import get_session_factory
from sauron_api.models import User

TEST_SETTINGS = Settings(
    database_url="sqlite+aiosqlite:///:memory:",
    consumer_enabled=False,
    auth_enabled=True,
    secret_key="test-secret",
    ingest_token="ingest-tok",
)


@pytest.fixture
async def auth_on():
    """Enable auth with a known secret for the duration of a test."""
    previous = config._settings
    config._settings = TEST_SETTINGS
    yield
    config._settings = previous


async def _make_user(email: str, role: str, password: str = "pw") -> User:
    async with get_session_factory()() as session:
        user = User(email=email, role=role, hashed_password=hash_password(password))
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def test_login_and_me(client, auth_on):
    await _make_user("op@sauron.dev", "admin", "s3cret")
    bad = await client.post(
        "/api/v1/auth/login", json={"email": "op@sauron.dev", "password": "wrong"}
    )
    assert bad.status_code == 401

    ok = await client.post(
        "/api/v1/auth/login", json={"email": "op@sauron.dev", "password": "s3cret"}
    )
    assert ok.status_code == 200
    token = ok.json()["access_token"]
    assert ok.json()["role"] == "admin"

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "op@sauron.dev"


async def test_protected_endpoints_require_token(client, auth_on):
    assert (await client.get("/api/v1/cameras")).status_code == 401
    assert (await client.get("/api/v1/events")).status_code == 401
    assert (await client.get("/api/v1/kpis")).status_code == 401
    # branding stays public so the login page can render the brand
    branding = await client.get("/api/v1/branding")
    assert branding.status_code == 200
    assert branding.json()["auth_required"] is True


async def test_viewer_cannot_write(client, auth_on):
    viewer = await _make_user("view@sauron.dev", "viewer")
    admin = await _make_user("root@sauron.dev", "admin")
    v_token = create_token(viewer)
    a_token = create_token(admin)

    ok = await client.get("/api/v1/cameras", headers={"Authorization": f"Bearer {v_token}"})
    assert ok.status_code == 200

    forbidden = await client.post(
        "/api/v1/cameras",
        json={"name": "x", "stream_id": "s-x"},
        headers={"Authorization": f"Bearer {v_token}"},
    )
    assert forbidden.status_code == 403

    allowed = await client.post(
        "/api/v1/cameras",
        json={"name": "x", "stream_id": "s-x"},
        headers={"Authorization": f"Bearer {a_token}"},
    )
    assert allowed.status_code == 201


async def test_ingest_token_flow(client, auth_on):
    payload = {
        "event_type": "WRONG_WAY",
        "camera_id": "cam-auth",
        "timestamp": 1786000000.0,
        "confidence": 0.9,
        "metadata": {},
    }
    no_token = await client.post("/api/v1/events", json=payload)
    assert no_token.status_code == 401

    with_token = await client.post(
        "/api/v1/events",
        json=payload,
        headers={"Authorization": "Bearer ingest-tok"},
    )
    assert with_token.status_code == 202


def test_token_roundtrip():
    config._settings = TEST_SETTINGS
    try:
        user = User(email="t@t.dev", role="viewer", hashed_password="")
        token = create_token(user)
        payload = decode_token(token)
        assert payload["email"] == "t@t.dev"
        assert payload["role"] == "viewer"
    finally:
        config._settings = None
