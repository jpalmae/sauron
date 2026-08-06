import numpy as np

from sauron_inference.pipeline.clip import ClipBuffer
from sauron_inference.types import Frame


def frame(ts: float, value: int = 64) -> Frame:
    img = np.full((120, 160, 3), value, dtype=np.uint8)
    return Frame(camera_id="cam-c", seq=int(ts * 15), image=img, timestamp=ts)


def test_buffer_bounded_by_preroll():
    buf = ClipBuffer(preroll_seconds=1.0, fps=10)
    for i in range(30):
        buf.add(frame(i / 10))
    assert len(buf._frames) == 10  # 1s at 10fps


def test_render_mp4_produces_valid_file():
    buf = ClipBuffer(preroll_seconds=2.0, fps=15, clip_fps=10)
    for i in range(20):
        buf.add(frame(i / 15, value=32 + i))
    mp4 = buf.render_mp4()
    assert mp4 is not None
    assert b"ftyp" in mp4[:16]  # MP4 signature
    assert len(mp4) > 1000


def test_render_too_short_returns_none():
    buf = ClipBuffer()
    buf.add(frame(0.0))
    assert buf.render_mp4() is None
    assert ClipBuffer().render_mp4() is None
