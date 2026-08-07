
import httpx

from sauron_inference.camera_sync import APICameraSource
from sauron_inference.config import DefaultsConfig, PipelineConfig, StreamConfig


def _source(monkeypatch, cameras):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/cameras/active")
        assert request.headers.get("Authorization") == "Bearer tok"
        return httpx.Response(200, json=cameras)

    src = APICameraSource("http://api:8000", "tok", DefaultsConfig())
    monkeypatch.setattr(
        src, "_client", httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api:8000")
    )
    return src


def test_maps_active_cameras_to_streams(monkeypatch):
    src = _source(
        monkeypatch,
        [
            {
                "stream_id": "cam-a",
                "name": "Cam A",
                "rtsp_url": "rtsp://a/1",
                "roi_config": {"lines": [{"id": "L1", "points": [[0, 1], [2, 3]]}]},
            },
            {"stream_id": "cam-empty", "name": "Sin URL", "rtsp_url": ""},
        ],
    )
    streams = src.fetch_streams()
    assert len(streams) == 1  # empty rtsp_url is skipped
    s = streams[0]
    assert s.id == "cam-a"
    assert s.source == "rtsp://a/1"
    assert s.type == "rtsp"
    assert s.roi is not None and s.roi.lines[0].id == "L1"


def test_invalid_roi_config_is_ignored(monkeypatch):
    src = _source(
        monkeypatch,
        [{"stream_id": "cam-b", "name": "B", "rtsp_url": "rtsp://b", "roi_config": {"lines": [{"id": "bad"}]}}],
    )
    streams = src.fetch_streams()
    assert streams[0].roi is None


def test_reconcile_starts_and_stops(monkeypatch):
    from sauron_inference.pipeline.manager import PipelineManager

    cfg = PipelineConfig(streams=[], defaults=DefaultsConfig())
    manager = PipelineManager(cfg, detector_factory=lambda *a, **k: None, source_factory=lambda *a, **k: None)

    started, stopped = [], []
    monkeypatch.setattr(manager, "_start_one", lambda s: started.append(s.id))

    class FakePipeline:
        def __init__(self, cid):
            self.source = type("S", (), {"camera_id": cid})()

        def stop(self):
            stopped.append(self.source.camera_id)

    manager.pipelines = [FakePipeline("old-cam")]
    manager._stream_hashes = {"old-cam": "h1"}

    manager.reconcile([StreamConfig(id="new-cam", source="rtsp://n"), StreamConfig(id="old-cam", source="rtsp://other")])
    # old-cam's hash changed -> stopped and restarted; new-cam started
    assert "old-cam" in stopped
    assert set(started) == {"new-cam", "old-cam"}


def test_reconcile_keeps_matching(monkeypatch):
    from sauron_inference.pipeline.manager import PipelineManager

    cfg = PipelineConfig(streams=[], defaults=DefaultsConfig())
    manager = PipelineManager(cfg, detector_factory=lambda *a, **k: None, source_factory=lambda *a, **k: None)
    monkeypatch.setattr(manager, "_start_one", lambda s: (_ for _ in ()).throw(AssertionError("should not start")))

    stream = StreamConfig(id="keep", source="rtsp://k")

    class FakePipeline:
        source = type("S", (), {"camera_id": "keep"})()

        def stop(self):
            raise AssertionError("should not stop")

    manager.pipelines = [FakePipeline()]
    manager._stream_hashes = {"keep": manager._hash(stream)}
    manager.reconcile([stream])  # same hash -> untouched
