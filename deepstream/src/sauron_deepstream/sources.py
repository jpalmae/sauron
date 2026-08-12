from __future__ import annotations

from urllib.parse import urlparse


def resolve_source(value: str) -> str:
    """Validate a camera URI without invoking a model-specific legacy resolver."""
    uri = value.strip()
    parsed = urlparse(uri)
    if parsed.scheme not in {"rtsp", "rtsps", "http", "https", "file"}:
        raise ValueError(f"unsupported camera URI scheme: {parsed.scheme or 'missing'}")
    if parsed.netloc.endswith("youtube.com") or parsed.netloc.endswith("youtu.be"):
        raise ValueError("web watch pages are not camera streams; provide RTSP or direct HLS")
    return uri
