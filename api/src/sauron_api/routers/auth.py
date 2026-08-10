from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import create_token, get_current_user, verify_password
from ..config import get_settings
from ..db import get_session
from ..models import User
from ..oidc import (
    authorize_url,
    discover,
    email_from_claims,
    exchange_code,
    get_providers,
    validate_id_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    email: str
    role: str


class MeResponse(BaseModel):
    email: str
    role: str


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, session: AsyncSession = Depends(get_session)):
    if not get_settings().auth_enabled:
        raise HTTPException(400, "auth is disabled")
    result = await session.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(
        payload.password, user.hashed_password
    ):
        raise HTTPException(401, "invalid credentials")
    return LoginResponse(access_token=create_token(user), email=user.email, role=user.role)


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(get_current_user)):
    return MeResponse(email=user.email, role=user.role)


# ---------- SSO (OIDC: MS365 / Google Workspace) ----------


@router.get("/oidc/{provider}/login")
async def oidc_login(provider: str):
    providers = get_providers()
    p = providers.get(provider)
    if p is None:
        raise HTTPException(404, f"SSO provider '{provider}' not configured")
    await discover(p)
    settings = get_settings()
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    redirect_uri = f"{settings.oidc_redirect_base}/api/v1/auth/oidc/callback"
    url = authorize_url(p, state, redirect_uri, nonce)
    resp = RedirectResponse(url)
    resp.set_cookie("oidc_state", state, httponly=True, max_age=600, samesite="lax")
    resp.set_cookie("oidc_nonce", nonce, httponly=True, max_age=600, samesite="lax")
    resp.set_cookie("oidc_provider", provider, httponly=True, max_age=600, samesite="lax")
    return resp


@router.get("/oidc/callback")
async def oidc_callback(
    code: str,
    state: str,
    session: AsyncSession = Depends(get_session),
    oidc_state: Annotated[str | None, Cookie()] = None,
    oidc_nonce: Annotated[str | None, Cookie()] = None,
    oidc_provider: Annotated[str | None, Cookie()] = None,
):
    if not oidc_state or state != oidc_state:
        raise HTTPException(400, "invalid state (possible CSRF)")
    p = get_providers().get(oidc_provider or "")
    if p is None:
        raise HTTPException(400, "unknown SSO provider in flow")
    await discover(p)

    settings = get_settings()
    redirect_uri = f"{settings.oidc_redirect_base}/api/v1/auth/oidc/callback"
    tokens = await exchange_code(p, code, redirect_uri)
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(502, "provider did not return an id_token")
    try:
        claims = await validate_id_token(p, id_token, oidc_nonce or "")
        email = email_from_claims(oidc_provider or "", claims)
    except ValueError as e:
        raise HTTPException(401, f"SSO validation failed: {e}") from None

    domain = email.split("@")[-1]
    allowed = [d.strip().lower() for d in settings.oidc_allowed_domains.split(",") if d.strip()]
    if allowed and domain not in allowed:
        raise HTTPException(403, f"domain '{domain}' not allowed")

    result = await session.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()
    if user is None:
        # first SSO user becomes admin when no users exist at all
        count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        user = User(
            email=email,
            hashed_password="",
            role="admin" if count == 0 else "viewer",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    if not user.is_active:
        raise HTTPException(403, "user disabled")

    token = create_token(user)
    resp = RedirectResponse(f"/login?token={token}", status_code=303)
    resp.delete_cookie("oidc_state")
    resp.delete_cookie("oidc_nonce")
    resp.delete_cookie("oidc_provider")
    return resp
