import numpy as np

from sauron_inference.audio import PeakDetector


def _pcm(level: float, n: int = 16000) -> np.ndarray:
    rng = np.random.default_rng(1)
    return (rng.normal(0, level, n)).astype(np.int16)


def test_peak_detector_fires_on_loud_bang():
    d = PeakDetector(peak_factor=4.0, window=10)
    for _ in range(15):
        assert d.feed(_pcm(50)) is None  # baseline ruido ambiente
    hit = d.feed(_pcm(2000))  # "bang"
    assert hit is not None
    assert hit > 500


def test_peak_detector_cooldown():
    d = PeakDetector(peak_factor=4.0, window=10)
    d.cooldown_s = 0.2
    for _ in range(15):
        d.feed(_pcm(50))
    assert d.feed(_pcm(2000)) is not None
    # inmediatamente después: cooldown
    assert d.feed(_pcm(2000)) is None


def test_peak_detector_ignores_silence_and_empty():
    d = PeakDetector()
    assert d.feed(np.array([], dtype=np.int16)) is None
    assert d.feed(np.zeros(16000, dtype=np.int16)) is None
