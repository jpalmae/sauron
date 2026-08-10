import numpy as np

from sauron_inference.config import PrivacyConfig
from sauron_inference.rules.privacy import redact_frame
from sauron_inference.types import TrackedObject


def track(cx, cy, cls, w=60, h=100):
    return TrackedObject(
        object_id=1, camera_id="c", class_name=cls, class_id=0,
        bbox=(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), score=0.9,
        centroid=(cx, cy), velocity=(0, 0), track_history=[], frame_seq=1, timestamp=1.0,
    )


def _striped(w=200, h=200):
    img = np.zeros((h, w, 3), np.uint8)
    img[:, ::2] = 255
    return img


def _var(img, x1, y1, x2, y2):
    return float(img[y1:y2, x1:x2].var())


def test_blur_faces_blurs_top_third_only():
    img = _striped()
    cfg = PrivacyConfig(blur_faces=True, blur_plates=False)
    out = redact_frame(img, [track(100, 100, "person")], cfg)
    # person bbox: (70,50)-(130,150); top third y 50..83
    assert _var(out, 75, 55, 125, 80) < _var(img, 75, 55, 125, 80) * 0.5
    # lower body untouched
    assert _var(out, 75, 120, 125, 145) == _var(img, 75, 120, 125, 145)
    # original image untouched (works on a copy)
    assert _var(img, 75, 55, 125, 80) > 0


def test_blur_plates_on_vehicle_band():
    img = _striped()
    cfg = PrivacyConfig(blur_faces=False, blur_plates=True)
    out = redact_frame(img, [track(100, 100, "car")], cfg)
    # car bbox (70,50)-(130,150); plate band y ~105..150
    assert _var(out, 75, 120, 125, 145) < _var(img, 75, 120, 125, 145) * 0.5
    # windshield area untouched
    assert _var(out, 75, 60, 125, 80) == _var(img, 75, 60, 125, 80)


def test_disabled_privacy_returns_identical():
    img = _striped()
    cfg = PrivacyConfig(blur_faces=False, blur_plates=False)
    out = redact_frame(img, [track(100, 100, "person")], cfg)
    assert np.array_equal(out, img)
