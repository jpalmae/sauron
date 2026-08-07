import sys
import types

from sauron_inference.capture import resolve


def _fake_yt_dlp(urls):
    calls = []

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def extract_info(self, url, download=False):
            calls.append(url)
            return {"url": urls[len(calls) - 1]}

    mod = types.ModuleType("yt_dlp")
    mod.YoutubeDL = FakeYDL
    return mod, calls


def test_plain_sources_pass_through():
    assert resolve.resolve_source("rtsp://cam/1") == "rtsp://cam/1"
    assert resolve.resolve_source("https://cam/playlist.m3u8") == "https://cam/playlist.m3u8"


def test_yt_source_resolves_and_caches(monkeypatch):
    fake, calls = _fake_yt_dlp(["https://manifest/one.m3u8", "https://manifest/two.m3u8"])
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    resolve._cache.clear()

    url1 = resolve.resolve_source("yt:https://youtube.com/watch?v=x")
    assert url1 == "https://manifest/one.m3u8"
    # second call hits the cache (no re-extract)
    url2 = resolve.resolve_source("yt:https://youtube.com/watch?v=x")
    assert url2 == url1
    assert len(calls) == 1


def test_yt_cache_expires(monkeypatch):
    fake, calls = _fake_yt_dlp(["https://manifest/a.m3u8", "https://manifest/b.m3u8"])
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    resolve._cache.clear()

    resolve.resolve_source("yt:https://youtube.com/watch?v=y")
    # force expiry
    resolve._cache["https://youtube.com/watch?v=y"] = (0.0, "https://manifest/a.m3u8")
    url = resolve.resolve_source("yt:https://youtube.com/watch?v=y")
    assert url == "https://manifest/b.m3u8"
    assert len(calls) == 2
