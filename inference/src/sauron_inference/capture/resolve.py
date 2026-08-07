from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

_cache: dict[str, tuple[float, str]] = {}
_CACHE_TTL_S = 4 * 3600  # googlevideo URLs expire; refresh well before


def resolve_source(source: str) -> str:
    """Resolve stream source URLs. Supports `yt:<youtube-url>` via yt-dlp.

    The resolved HLS URL is cached for ~4h; re-resolution happens on cache
    expiry and on every reconnect cycle (RTSPSource calls this per attempt).
    """
    if not source.startswith("yt:"):
        return source
    watch_url = source[3:]
    cached = _cache.get(watch_url)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL_S:
        return cached[1]
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("yt: sources require the `live` extra (yt-dlp)") from e
    with yt_dlp.YoutubeDL({"quiet": True, "format": "b[height<=720][protocol=m3u8_native]/b"}) as ydl:
        info = ydl.extract_info(watch_url, download=False)
        url = info["url"]
    _cache[watch_url] = (time.monotonic(), url)
    log.info("resolved %s -> live HLS manifest", watch_url)
    return url
