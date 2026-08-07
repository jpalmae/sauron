from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from urllib.parse import urlparse

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import decode_token, get_current_user
from ..config import get_settings
from ..db import get_session
from ..models import Camera, User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/streams", tags=["streams"])

_resolve_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL_S = 300  # googlevideo manifests expire; re-resolve every 5 min max
_allowed_hosts: set[str] = set()
_http: httpx.AsyncClient | None = None


def _http_client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=15.0, follow_redirects=True)
    return _http


async def hls_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Auth via Authorization header or ?token= (HLS players can't set headers)."""
    settings = get_settings()
    if not settings.auth_enabled:
        return
    token = request.query_params.get("token", "")
    authz = request.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        token = authz[7:]
    user = None
    try:
        payload = decode_token(token)
        user = await session.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        user = None
    if user is None or not user.is_active:
        raise HTTPException(401, "unauthorized")


class LiveUrl(BaseModel):
    kind: str  # "hls" | "whep" | "none"
    url: str


def _is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url


def _resolve_youtube(watch_url: str) -> str:
    cached = _resolve_cache.get(watch_url)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL_S:
        return cached[1]
    import yt_dlp

    with yt_dlp.YoutubeDL(
        {"quiet": True, "format": "b[height<=720][protocol=m3u8_native]/b"}
    ) as ydl:
        info = ydl.extract_info(watch_url, download=False)
        url = info["url"]
    _resolve_cache[watch_url] = (time.monotonic(), url)
    return url


@router.get("/{stream_id}/live-url", response_model=LiveUrl)
async def live_url(
    stream_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(get_current_user),
):
    """Best live playback URL for a camera.

    - rtsp:// -> WHEP path on the MediaMTX gateway
    - YouTube/HLS -> freshly resolved m3u8 for the embedded HLS player
    """
    result = await session.execute(select(Camera).where(Camera.stream_id == stream_id))
    camera = result.scalar_one_or_none()
    if camera is None:
        raise HTTPException(404, "camera not found")

    src = camera.rtsp_url or ""
    settings = get_settings()
    if src.startswith("rtsp://") and settings.live_go2rtc_enabled:
        # puente go2rtc (Xiaomi/Mi Home, etc.): WHEP same-origin via nginx /go2rtc/
        name = urlparse(src).path.strip("/") or stream_id
        return LiveUrl(kind="whep", url=f"/go2rtc/api/webrtc?src={name}")
    if src.startswith("rtsp://"):
        return LiveUrl(kind="whep", url=f"/whep/{stream_id}")
    if _is_youtube(src) or ".m3u8" in src:
        # same-origin proxy: HLS manifests/segments have no CORS headers
        return LiveUrl(kind="hls", url=f"/api/v1/streams/{stream_id}/hls/playlist.m3u8")
    return LiveUrl(kind="none", url="")


async def _source_url(camera: Camera) -> str:
    src = camera.rtsp_url or ""
    if _is_youtube(src):
        try:
            return await asyncio.to_thread(_resolve_youtube, src)
        except Exception as e:  # noqa: BLE001 - yt-dlp raises many types; 502 either way
            log.warning("youtube resolve failed for %s: %s", camera.stream_id, e)
            raise HTTPException(502, "live stream resolution failed") from None
    return src


def _rewrite_manifest(manifest: str, base_url: str, stream_id: str, token: str = "") -> str:
    """Point every variant/segment URL at the same-origin proxy."""
    suffix = f"&token={token}" if token else ""
    out: list[str] = []
    for line in manifest.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            absolute = stripped if stripped.startswith("http") else f"{base_url}/{stripped}"
            host = urlparse(absolute).netloc
            _allowed_hosts.add(host)
            token_b64 = base64.urlsafe_b64encode(absolute.encode()).decode()
            line = f"/api/v1/streams/{stream_id}/hls/proxy?u={token_b64}{suffix}"
        out.append(line)
    return "\n".join(out) + "\n"


@router.get("/{stream_id}/hls/playlist.m3u8")
async def hls_playlist(
    stream_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: None = Depends(hls_user),
):
    result = await session.execute(select(Camera).where(Camera.stream_id == stream_id))
    camera = result.scalar_one_or_none()
    if camera is None:
        raise HTTPException(404, "camera not found")
    url = await _source_url(camera)
    resp = await _http_client().get(url)
    if resp.status_code != 200:
        raise HTTPException(502, f"upstream manifest error: {resp.status_code}")
    base = url.rsplit("/", 1)[0]
    token = request.query_params.get("token", "")
    body = _rewrite_manifest(resp.text, base, stream_id, token)
    return Response(
        body, media_type="application/vnd.apple.mpegurl", headers={"Cache-Control": "no-store"}
    )


@router.get("/{stream_id}/hls/proxy")
async def hls_proxy(
    stream_id: str,
    u: str,
    _: None = Depends(hls_user),
):
    try:
        url = base64.urlsafe_b64decode(u.encode()).decode()
    except ValueError:
        raise HTTPException(400, "bad proxy token") from None
    host = urlparse(url).netloc
    if host not in _allowed_hosts:
        raise HTTPException(403, "host not allowed")

    async def stream():
        client = _http_client()
        async with client.stream("GET", url, timeout=30.0) as resp:
            async for chunk in resp.aiter_bytes(64 * 1024):
                yield chunk

    return StreamingResponse(stream(), media_type="video/mp2t")
