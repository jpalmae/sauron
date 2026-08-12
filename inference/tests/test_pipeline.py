import threading
import time

from sauron_inference.capture.synthetic import SyntheticSource
from sauron_inference.detection.mock import MockDetector
from sauron_inference.pipeline.stream import StreamPipeline
from sauron_inference.rules.events import Event, EventType, Priority
from sauron_inference.tracking.bytetrack import BYTETracker


def test_pipeline_produces_persistent_tracks():
    received = []
    event = threading.Event()

    def on_tracks(camera_id, frame, tracks):
        if tracks:
            received.append(tracks)
            if len(received) >= 15:
                event.set()

    pipeline = StreamPipeline(
        source=SyntheticSource("cam-t", n_objects=3, target_fps=60, max_frames=60),
        detector=MockDetector(),
        tracker=BYTETracker(frame_rate=60),
        on_tracks=on_tracks,
    )
    pipeline.start()
    assert event.wait(timeout=15)
    pipeline.stop()

    first = received[0]
    last = received[-1]
    assert len(first) == 3
    assert len(last) == 3
    # IDs persist for the same synthetic objects
    assert {t.object_id for t in first} == {t.object_id for t in last}
    # centroid moves over time
    assert last[0].centroid != first[0].centroid
    assert last[0].track_history


def test_pipeline_bounded_queue_drops_frames():
    processed = []

    def on_tracks(camera_id, frame, tracks):
        time.sleep(0.05)  # slow consumer
        processed.append(frame.seq)

    pipeline = StreamPipeline(
        source=SyntheticSource("cam-slow", target_fps=120, max_frames=40),
        detector=MockDetector(),
        tracker=BYTETracker(frame_rate=120),
        on_tracks=on_tracks,
        queue_size=2,
    )
    pipeline.start()
    deadline = time.monotonic() + 15
    while pipeline.alive and time.monotonic() < deadline:
        time.sleep(0.1)
    pipeline.stop()

    assert pipeline.frames_captured == 40
    assert pipeline.frames_dropped > 0
    assert pipeline.frames_processed + pipeline.frames_dropped <= pipeline.frames_captured


def test_pipeline_stops_cleanly_without_frames():
    pipeline = StreamPipeline(
        source=SyntheticSource("cam-x", target_fps=30, max_frames=5),
        detector=MockDetector(),
        tracker=BYTETracker(),
    )
    pipeline.start()
    deadline = time.monotonic() + 10
    while pipeline.alive and time.monotonic() < deadline:
        time.sleep(0.1)
    pipeline.stop()
    assert not pipeline.alive


def test_evidence_rendering_does_not_block_inference():
    render_started = threading.Event()
    release_render = threading.Event()
    event_published = threading.Event()

    class OneShotRules:
        privacy = None

        def __init__(self):
            self.done = False

        def process(self, frame, tracks):
            if self.done:
                return []
            self.done = True
            return [
                Event(
                    event_type=EventType.STOPPED_VEHICLE,
                    camera_id=frame.camera_id,
                    timestamp=frame.timestamp,
                    confidence=0.9,
                    priority=Priority.WARNING,
                    rule_id="test",
                )
            ]

    class SlowClipBuffer:
        def add(self, *args):
            pass

        def snapshot(self):
            return (b"frame-1", b"frame-2")

        def render_mp4(self, frames):
            render_started.set()
            assert release_render.wait(timeout=5)
            return b"mp4"

    pipeline = StreamPipeline(
        source=SyntheticSource("cam-events", target_fps=120, max_frames=80),
        detector=MockDetector(),
        tracker=BYTETracker(frame_rate=120),
        rules_engine=OneShotRules(),
        clip_buffer=SlowClipBuffer(),
        on_event=lambda event: event_published.set(),
    )
    pipeline.start()
    assert render_started.wait(timeout=5)
    deadline = time.monotonic() + 2
    while pipeline.frames_processed < 10 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pipeline.frames_processed >= 10
    assert not event_published.is_set()
    release_render.set()
    assert event_published.wait(timeout=5)
    pipeline.stop()
