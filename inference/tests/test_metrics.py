import time

import numpy as np

from sauron_inference.metrics import StreamMetrics, make_handler
from sauron_inference.types import Frame, TrackedObject


def make_track(oid: int = 1) -> TrackedObject:
    return TrackedObject(
        object_id=oid,
        camera_id="cam-m",
        class_name="car",
        class_id=2,
        bbox=(0, 0, 10, 10),
        score=0.9,
        centroid=(5, 5),
        velocity=(1, 0),
        track_history=[(5, 5)],
        frame_seq=1,
        timestamp=time.time(),
    )


def frame(ts: float) -> Frame:
    return Frame(camera_id="cam-m", seq=1, image=np.zeros((8, 8, 3), np.uint8), timestamp=ts)


def test_render_prometheus_format():
    m = StreamMetrics()
    ts = time.time()
    m.record_processed("cam-m", frame(ts), [make_track()])
    m.record_event("cam-m")
    m.sync_counters("cam-m", captured=100, dropped=3)
    text = m.render()

    assert 'sauron_frames_captured_total{camera="cam-m"} 100' in text
    assert 'sauron_frames_processed_total{camera="cam-m"} 1' in text
    assert 'sauron_frames_dropped_total{camera="cam-m"} 3' in text
    assert 'sauron_tracks_active{camera="cam-m"} 1' in text
    assert 'sauron_events_total{camera="cam-m"} 1' in text
    assert 'sauron_pipeline_latency_ms{camera="cam-m"}' in text
    assert "# HELP sauron_frames_captured_total" in text


def test_latency_computed_from_frame_timestamp():
    m = StreamMetrics()
    m.record_processed("cam-m", frame(time.time() - 0.5), [])
    for line in m.render().splitlines():
        if line.startswith("sauron_pipeline_latency_ms"):
            value = float(line.split()[-1])
            assert 400 < value < 2000


def test_handler_serves_metrics_and_healthz():
    import io

    m = StreamMetrics()
    handler_cls = make_handler(m)

    class FakeHandler(handler_cls):
        def __init__(self, path):
            self.path = path
            self.wfile = io.BytesIO()
            self._status = None

        def send_response(self, code):
            self._status = code

        def send_header(self, *a):
            pass

        def end_headers(self):
            pass

    h = FakeHandler("/metrics")
    h.do_GET()
    assert h._status == 200
    assert b"sauron_" in h.wfile.getvalue()

    h2 = FakeHandler("/healthz")
    h2.do_GET()
    assert h2._status == 200

    h3 = FakeHandler("/nope")
    h3.do_GET()
    assert h3._status == 404
