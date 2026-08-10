import numpy as np

from sauron_inference.alpr.crop import alpr_crop
from sauron_inference.alpr.ocr import TesseractOcr, normalize_plate
from sauron_inference.config import AlprConfig, ThresholdsConfig
from sauron_inference.rules.alpr import AlprRule
from sauron_inference.rules.base import RuleContext
from sauron_inference.rules.events import EventType, Priority
from sauron_inference.types import Frame, TrackedObject

CTX = RuleContext(camera_id="cam-a", fps=15, thresholds=ThresholdsConfig())


def track(oid, cx, cy, cls="car", ts=1.0, h=100):
    return TrackedObject(
        object_id=oid, camera_id="cam-a", class_name=cls, class_id=2,
        bbox=(cx - 80, cy - h / 2, cx + 80, cy + h / 2), score=0.9,
        centroid=(cx, cy), velocity=(5.0, 0.0), track_history=[(cx, cy)],
        frame_seq=int(ts * 15), timestamp=ts,
    )


def frame(ts, img=None):
    return Frame(camera_id="cam-a", seq=int(ts * 15),
                 image=img if img is not None else np.zeros((720, 1280, 3), np.uint8),
                 timestamp=ts)


class TestNormalize:
    def test_basic(self):
        assert normalize_plate("AB-123") == "AB123"
        assert normalize_plate("  gx-77-kp ") == "GX77KP"

    def test_too_short(self):
        assert normalize_plate("A1") == ""
        assert normalize_plate("...") == ""

    def test_longest_token(self):
        # toma el primer token plausible (4-9 alnum)
        assert normalize_plate("XX ABCDEFGH YY") in {"ABCDEFGH"}


class TestCrop:
    def test_vehicle_crop_lower_region(self):
        img = np.full((720, 1280, 3), 200, np.uint8)
        img[500:700, 400:600] = 255
        t = track(1, 500, 600, cls="car", h=200)
        crop = alpr_crop(img, t)
        assert crop is not None
        assert crop.shape[0] == 120  # lower 60% of 200px bbox
        assert crop.mean() > 200

    def test_skips_non_vehicle_and_tiny(self):
        img = np.zeros((720, 1280, 3), np.uint8)
        assert alpr_crop(img, track(1, 100, 100, cls="person")) is None
        assert alpr_crop(img, track(1, 100, 100, cls="car", h=20)) is None


class FakeOcr(TesseractOcr):
    def __init__(self, result):
        self._result = result
        self.calls = 0

    def read_plate(self, crop):
        self.calls += 1
        return self._result


class TestAlprRule:
    def test_emits_alpr_event_once_per_track(self):
        cfg = AlprConfig(enabled=True, watchlist=[])
        ocr = FakeOcr(("ABC123", 0.9))
        rule = AlprRule(cfg, ocr)
        f = frame(1.0)
        t = track(1, 500, 300)

        events = rule.process(f, [t], CTX)
        assert len(events) == 1
        e = events[0]
        assert e.event_type == EventType.ALPR
        assert e.priority == Priority.INFO
        assert e.metadata["plate_text"] == "ABC123"

        # already read -> throttled (no new OCR)
        assert rule.process(frame(2.0), [track(1, 510, 300, ts=2.0)], CTX) == []
        assert ocr.calls == 1

    def test_watchlist_escalates_to_critical(self):
        cfg = AlprConfig(enabled=True, watchlist=["ZZ-999"])
        rule = AlprRule(cfg, FakeOcr(("ZZ999", 0.8)))
        events = rule.process(frame(1.0), [track(1, 500, 300)], CTX)
        assert events[0].event_type == EventType.ALPR_WATCHLIST
        assert events[0].priority == Priority.CRITICAL
        assert events[0].metadata["watchlist"] is True

    def test_low_confidence_ignored(self):
        cfg = AlprConfig(enabled=True, min_confidence=0.5)
        rule = AlprRule(cfg, FakeOcr(("ABC123", 0.2)))
        assert rule.process(frame(1.0), [track(1, 500, 300)], CTX) == []

    def test_ocr_interval_throttling(self):
        cfg = AlprConfig(enabled=True, ocr_interval_frames=30)
        ocr = FakeOcr(("", 0.0))  # unreadable -> retried after interval
        rule = AlprRule(cfg, ocr)
        rule.process(frame(1.0), [track(1, 500, 300)], CTX)
        rule.process(frame(1.5), [track(1, 500, 300, ts=1.5)], CTX)  # seq 22 < 30
        assert ocr.calls == 1
        rule.process(frame(3.0), [track(1, 500, 300, ts=3.0)], CTX)  # seq 45 >= 30
        assert ocr.calls == 2
