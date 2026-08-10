from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from .config import get_settings

log = logging.getLogger(__name__)


@dataclass
class OIDCProvider:
    name: str
    issuer: str
    client_id: str
    client_secret: str
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    jwks_uri: str = ""


_providers: dict[str, OIDCProvider] | None = None


def get_providers() -> dict[str, OIDCProvider]:
    """Configured SSO providers (from SAURON_OIDC_PROVIDERS_JSON)."""
    global _providers
    if _providers is None:
        _providers = {}
        raw = get_settings().oidc_providers_json.strip()
        if raw:
            data = json.loads(raw)
            for name, cfg in data.items():
                _providers[name] = OIDCProvider(
                    name=name,
                    issuer=cfg["issuer"].rstrip("/"),
                    client_id=cfg["client_id"],
                    client_secret=cfg["client_secret"],
                )
    return _providers


async def discover(provider: OIDCProvider) -> OIDCProvider:
    """Fill endpoints from .well-known/openid-configuration (cached in-place)."""
    if provider.authorization_endpoint:
        return provider
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{provider.issuer}/.well-known/openid-configuration")
        resp.raise_for_status()
        meta = resp.json()
    provider.authorization_endpoint = meta["authorization_endpoint"]
    provider.token_endpoint = meta["token_endpoint"]
    provider.jwks_uri = meta["jwks_uri"]
    return provider


def authorize_url(provider: OIDCProvider, state: str, redirect_uri: str, nonce: str) -> str:
    from urllib.parse import urlencode

    params = {
        "client_id": provider.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
    }
    return f"{provider.authorization_endpoint}?{urlencode(params)}"


async def exchange_code(
    provider: OIDCProvider, code: str, redirect_uri: str
) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            provider.token_endpoint,
            data={
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def validate_id_token(provider: OIDCProvider, id_token: str, nonce: str) -> dict:
    """Validate signature (JWKS), issuer, audience, expiry and nonce."""
    from authlib.jose import JsonWebKey
    from authlib.jose import jwt as jose_jwt

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(provider.jwks_uri)
        resp.raise_for_status()
        jwks = JsonWebKey.import_key_set(resp.json())

    claims = jose_jwt.decode(id_token, jwks)
    claims.validate()
    if claims.get("iss") not in _valid_issuers(provider.issuer):
        raise ValueError(f"invalid issuer: {claims.get('iss')}")
    aud = claims.get("aud")
    if provider.client_id not in (aud if isinstance(aud, list) else [aud]):
        raise ValueError("invalid audience")
    if nonce and claims.get("nonce") != nonce:
        raise ValueError("nonce mismatch")
    return dict(claims)


def _valid_issuers(issuer: str) -> set[str]:
    # Microsoft: iss can differ in trailing /v2.0 vs /2.0 tenant forms
    return {issuer, issuer.rstrip("/"), issuer.replace("/v2.0", "/2.0")}


def email_from_claims(provider_name: str, claims: dict) -> str:
    email = claims.get("email") or claims.get("preferred_username") or claims.get("upn")
    if not email:
        raise ValueError("provider did not return an email claim")
    return str(email).lower()
