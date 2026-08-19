import os
import time
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from sauron_deepstream.evidence import EvidenceBox, EvidenceManager, EvidenceRequest
from sauron_deepstream.registry import Camera, CameraRegistry


def _manager(tmp_path: Path) -> EvidenceManager:
    settings = SimpleNamespace(
        evidence_dir=tmp_path,
        evidence_pre_seconds=5.0,
        evidence_post_seconds=10.0,
        evidence_segment_seconds=2.0,
        evidence_retention_seconds=120.0,
    )
    return EvidenceManager(settings, CameraRegistry())  # type: ignore[arg-type]


def _request(timestamp: float = 100.0) -> EvidenceRequest:
    return EvidenceRequest(
        event_id="event-1",
        event_type="WRONG_WAY",
        rule_id="lane-1",
        camera=Camera("cam-1", "Camera", "rtsp://camera/live", "traffic", None),
        timestamp=timestamp,
        object_id=7,
        frame_width=1280,
        frame_height=720,
        boxes=(EvidenceBox(7, "car", 0.94, (100, 100, 500, 400)),),
    )


def test_selects_only_segments_around_event(tmp_path: Path):
    manager = _manager(tmp_path)
    directory = manager._camera_directory("cam-1")
    directory.mkdir(parents=True)
    selected = directory / "segment-selected.mp4"
    selected.write_bytes(b"video")
    os.utime(selected, (104, 104))
    old = directory / "segment-old.mp4"
    old.write_bytes(b"video")
    os.utime(old, (50, 50))

    assert manager._segments_for_event(_request()) == [selected]


def test_annotates_snapshot_with_event_and_target_box(tmp_path: Path):
    manager = _manager(tmp_path)
    snapshot = tmp_path / "snapshot.jpg"
    Image.new("RGB", (640, 360), "white").save(snapshot, "JPEG")
    before = snapshot.read_bytes()

    manager._annotate_snapshot(snapshot, _request())

    assert snapshot.read_bytes() != before
    with Image.open(snapshot) as image:
        assert image.size == (640, 360)


def test_clip_is_trimmed_to_configured_event_window(tmp_path: Path, monkeypatch):
    manager = _manager(tmp_path)
    event_dir = tmp_path / "work"
    event_dir.mkdir()
    segment = tmp_path / "segment.mp4"
    segment.write_bytes(b"video")
    os.utime(segment, (96, 96))
    observed: list[str] = []

    def fake_run(command, **_kwargs):
        observed.extend(command)
        Path(command[-1]).write_bytes(b"clip")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("sauron_deepstream.evidence.subprocess.run", fake_run)

    clip = manager._build_clip(event_dir, [segment], _request(timestamp=100))

    assert clip is not None
    assert observed[observed.index("-ss") + 1] == "1.000"
    assert observed[observed.index("-t") + 1] == "15.000"


def test_cleanup_removes_abandoned_work_directories(tmp_path: Path):
    manager = _manager(tmp_path)
    abandoned = tmp_path / "work" / "old-event"
    abandoned.mkdir(parents=True)
    os.utime(abandoned, (time.time() - 121, time.time() - 121))

    manager._cleanup_segments()

    assert not abandoned.exists()
