
from sauron_api.routers.streams import _is_youtube, _resolve_cache, _resolve_youtube


def test_is_youtube():
    assert _is_youtube("https://www.youtube.com/watch?v=abc")
    assert _is_youtube("https://youtu.be/abc")
    assert not _is_youtube("rtsp://cam/1")
    assert not _is_youtube("https://cam/playlist.m3u8")


def test_resolve_youtube_caches(monkeypatch):
    import sys
    import types

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
            return {"url": f"https://manifest/{len(calls)}.m3u8"}

    mod = types.ModuleType("yt_dlp")
    mod.YoutubeDL = FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", mod)
    _resolve_cache.clear()

    assert _resolve_youtube("https://youtu.be/x") == "https://manifest/1.m3u8"
    assert _resolve_youtube("https://youtu.be/x") == "https://manifest/1.m3u8"
    assert len(calls) == 1


async def test_live_url_kinds(client):
    # rtsp -> whep path
    await client.post(
        "/api/v1/cameras",
        json={"name": "RTSP cam", "stream_id": "rtsp-cam", "rtsp_url": "rtsp://cam/1"},
    )
    resp = await client.get("/api/v1/streams/rtsp-cam/live-url")
    assert resp.json() == {"kind": "whep", "url": "/whep/rtsp-cam"}

    # plain hls -> same-origin proxy path
    await client.post(
        "/api/v1/cameras",
        json={
            "name": "HLS cam",
            "stream_id": "hls-cam",
            "rtsp_url": "https://cam/playlist.m3u8",
        },
    )
    resp = await client.get("/api/v1/streams/hls-cam/live-url")
    assert resp.json() == {"kind": "hls", "url": "/api/v1/streams/hls-cam/hls/playlist.m3u8"}

    # no source -> none
    await client.post("/api/v1/cameras", json={"name": "x", "stream_id": "empty-cam"})
    resp = await client.get("/api/v1/streams/empty-cam/live-url")
    assert resp.json()["kind"] == "none"

    assert (await client.get("/api/v1/streams/nope/live-url")).status_code == 404


async def test_live_url_youtube(monkeypatch, client):
    import sys
    import types

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def extract_info(self, url, download=False):
            return {"url": "https://manifest/live.m3u8"}

    mod = types.ModuleType("yt_dlp")
    mod.YoutubeDL = FakeYDL
    monkeypatch.setitem(sys.modules, "yt_dlp", mod)
    _resolve_cache.clear()

    await client.post(
        "/api/v1/cameras",
        json={
            "name": "YT cam",
            "stream_id": "yt-cam",
            "rtsp_url": "https://www.youtube.com/watch?v=gFRtAAmiFbE",
        },
    )
    resp = await client.get("/api/v1/streams/yt-cam/live-url")
    assert resp.json() == {"kind": "hls", "url": "/api/v1/streams/yt-cam/hls/playlist.m3u8"}


def test_rewrite_manifest():
    from sauron_api.routers.streams import _allowed_hosts, _rewrite_manifest

    _allowed_hosts.clear()
    manifest = (
        "#EXTM3U\n"
        "#EXT-X-TARGETDURATION:5\n"
        "#EXTINF:5.0,\n"
        "https://rr1---sn-abc.googlevideo.com/videoplayback/seg1.ts\n"
        "seg2.ts\n"
    )
    out = _rewrite_manifest(manifest, "https://media.example.com/D3/x.stream", "cam-1")
    lines = out.splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[2].startswith("#EXTINF")
    assert lines[3].startswith("/api/v1/streams/cam-1/hls/proxy?u=")
    assert lines[4].startswith("/api/v1/streams/cam-1/hls/proxy?u=")
    assert "rr1---sn-abc.googlevideo.com" in _allowed_hosts
    assert "media.example.com" in _allowed_hosts
