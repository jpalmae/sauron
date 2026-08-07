from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_session
from .models import User

_pwd = PasswordHash.recommended()
_bearer = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _pwd.verify(password, hashed)


def create_token(user: User) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.token_ttl_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Authenticated user. No-op (synthetic admin) when auth is disabled."""
    settings = get_settings()
    if not settings.auth_enabled:
        return User(
            id=uuid.UUID(int=0), email="dev@local", hashed_password="", role="admin"
        )
    if credentials is None:
        raise HTTPException(401, "missing bearer token")
    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid or expired token") from None
    user = await session.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(401, "user not found or inactive")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "admin role required")
    return user


async def require_ingest(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Event ingest: static ingest token, admin JWT, or open when auth disabled."""
    settings = get_settings()
    if not settings.auth_enabled:
        return
    token = credentials.credentials if credentials else None
    if token and settings.ingest_token and token == settings.ingest_token:
        return
    # fall back to an admin JWT
    if token:
        try:
            payload = decode_token(token)
            if payload.get("role") == "admin":
                user = await session.get(User, uuid.UUID(payload["sub"]))
                if user is not None and user.is_active:
                    return
        except (jwt.PyJWTError, KeyError, ValueError):
            pass
    raise HTTPException(401, "valid ingest token or admin JWT required")


async def ws_auth(ws: WebSocket, session: AsyncSession) -> None:
    """Validate ?token= for WebSocket clients (no-op when auth is disabled)."""
    from fastapi import WebSocketException

    settings = get_settings()
    if not settings.auth_enabled:
        return
    token = ws.query_params.get("token", "")
    user: User | None = None
    try:
        payload = decode_token(token)
        user = await session.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        user = None
    if user is None or not user.is_active:
        raise WebSocketException(code=4401, reason="unauthorized")


async def ensure_bootstrap_admin(session: AsyncSession) -> None:
    """Create the bootstrap admin on first start when auth is enabled."""
    settings = get_settings()
    if not settings.auth_enabled or not settings.admin_password:
        return
    result = await session.execute(select(User).limit(1))
    if result.scalar_one_or_none() is not None:
        return
    session.add(
        User(
            email=settings.admin_email,
            hashed_password=hash_password(settings.admin_password),
            role="admin",
        )
    )
    await session.commit()
