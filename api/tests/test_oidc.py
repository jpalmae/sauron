import json
import time

import pytest

from sauron_api import config
from sauron_api.oidc import (
    OIDCProvider,
    _valid_issuers,
    authorize_url,
    email_from_claims,
    get_providers,
    validate_id_token,
)


@pytest.fixture(autouse=True)
def reset_providers():
    import sauron_api.oidc as oidc_mod

    oidc_mod._providers = None
    yield
    oidc_mod._providers = None
    config._settings = None


def _settings_with_ms():
    return config.Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        consumer_enabled=False,
        auth_enabled=True,
        secret_key="test-secret",
        oidc_providers_json=json.dumps(
            {
                "microsoft": {
                    "issuer": "https://login.microsoftonline.com/tenant-123/v2.0",
                    "client_id": "ms-client",
                    "client_secret": "ms-secret",
                },
                "google": {
                    "issuer": "https://accounts.google.com",
                    "client_id": "g-client",
                    "client_secret": "g-secret",
                },
            }
        ),
    )


def test_providers_parsing():
    config._settings = _settings_with_ms()
    providers = get_providers()
    assert set(providers) == {"microsoft", "google"}
    assert providers["microsoft"].client_id == "ms-client"


def test_authorize_url():
    p = OIDCProvider(
        name="microsoft",
        issuer="https://login.microsoftonline.com/t/v2.0",
        client_id="cid",
        client_secret="sec",
        authorization_endpoint="https://login.microsoftonline.com/t/oauth2/v2.0/authorize",
    )
    url = authorize_url(p, "state123", "http://app/callback", "nonce456")
    assert url.startswith("https://login.microsoftonline.com/t/oauth2/v2.0/authorize?")
    assert "client_id=cid" in url
    assert "state=state123" in url
    assert "nonce=nonce456" in url
    assert "redirect_uri=http%3A%2F%2Fapp%2Fcallback" in url


def test_valid_issuers_microsoft_variants():
    valid = _valid_issuers("https://login.microsoftonline.com/tenant/v2.0")
    assert "https://login.microsoftonline.com/tenant/v2.0" in valid
    assert "https://login.microsoftonline.com/tenant/2.0" in valid


def test_email_from_claims_variants():
    assert email_from_claims("google", {"email": "A@B.COM"}) == "a@b.com"
    assert email_from_claims("microsoft", {"preferred_username": "u@empresa.com"}) == "u@empresa.com"
    assert email_from_claims("microsoft", {"upn": "u2@empresa.com"}) == "u2@empresa.com"
    with pytest.raises(ValueError):
        email_from_claims("google", {})


async def test_validate_id_token(monkeypatch):
    import jwt as pyjwt

    # generate an EC keypair and sign a fake id_token
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "EC",
                "crv": "P-256",
                "kid": "k1",
                "x": _b64u(pub.x.to_bytes(32, "big")),
                "y": _b64u(pub.y.to_bytes(32, "big")),
            }
        ]
    }
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    provider = OIDCProvider(
        name="google",
        issuer="https://accounts.google.com",
        client_id="g-client",
        client_secret="s",
        jwks_uri="https://www.googleapis.com/oauth2/v3/certs",
    )

    token = pyjwt.encode(
        {
            "iss": "https://accounts.google.com",
            "aud": "g-client",
            "sub": "123",
            "email": "user@empresa.com",
            "nonce": "n-1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        pem,
        algorithm="ES256",
        headers={"kid": "k1"},
    )

    import httpx

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url):
            return httpx.Response(200, json=jwks, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout: FakeClient())
    claims = await validate_id_token(provider, token, "n-1")
    assert claims["email"] == "user@empresa.com"

    with pytest.raises(ValueError):
        await validate_id_token(provider, token, "wrong-nonce")


def _b64u(b: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(b).decode().rstrip("=")
