from __future__ import annotations

import hashlib
import logging
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from .domain import Event, TrackedObject
from .metrics import Metrics
from .registry import Camera, CameraRegistry
from .settings import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EvidenceBox:
    object_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class EvidenceRequest:
    event_id: str
    event_type: str
    rule_id: str
    camera: Camera
    timestamp: float
    object_id: int | None
    frame_width: int
    frame_height: int
    boxes: tuple[EvidenceBox, ...]


@dataclass(slots=True)
class _Recorder:
    camera: Camera
    directory: Path
    process: subprocess.Popen[bytes]


class EvidenceManager:
    """Maintain per-camera encoded ring buffers and attach event evidence asynchronously.

    FFmpeg copies the source codec into short segments, so the rolling pre-event buffer does
    not consume a second GPU decoder. Event workers concatenate the relevant segments,
    extract and annotate the event frame, then upload both artifacts to the API. The
    metadata path only performs a bounded queue insertion and never waits for disk/network.
    """

    def __init__(
        self, settings: Settings, registry: CameraRegistry, metrics: Metrics | None = None
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._metrics = metrics
        self._requests: queue.Queue[EvidenceRequest] = queue.Queue(maxsize=512)
        self._recorders: dict[str, _Recorder] = {}
        self._recorders_lock = threading.RLock()
        self._stop = threading.Event()
        self._monitor: threading.Thread | None = None
        self._workers: list[threading.Thread] = []

    def start(self) -> None:
        if not self._settings.evidence_enabled or self._monitor is not None:
            return
        if shutil.which("ffmpeg") is None:
            log.error("event evidence disabled: ffmpeg is not installed")
            return
        self._settings.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._monitor = threading.Thread(
            target=self._monitor_recorders, name="evidence-recorders", daemon=True
        )
        self._monitor.start()
        for index in range(self._settings.evidence_workers):
            worker = threading.Thread(
                target=self._run_worker, name=f"evidence-worker-{index}", daemon=True
            )
            worker.start()
            self._workers.append(worker)
        log.info(
            "event evidence enabled: %.0fs pre / %.0fs post / %d workers",
            self._settings.evidence_pre_seconds,
            self._settings.evidence_post_seconds,
            self._settings.evidence_workers,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._monitor is not None:
            self._monitor.join(timeout=5)
        for worker in self._workers:
            worker.join(timeout=5)
        with self._recorders_lock:
            for recorder in self._recorders.values():
                _terminate(recorder.process)
            self._recorders.clear()

    def submit(
        self,
        event: Event,
        camera: Camera,
        tracks: list[TrackedObject],
        frame_width: int,
        frame_height: int,
    ) -> bool:
        if not self._settings.evidence_enabled or self._monitor is None:
            return False
        request = EvidenceRequest(
            event_id=event.event_id,
            event_type=str(event.event_type),
            rule_id=event.rule_id,
            camera=camera,
            timestamp=event.timestamp,
            object_id=event.object_id,
            frame_width=frame_width,
            frame_height=frame_height,
            boxes=tuple(
                EvidenceBox(
                    object_id=track.object_id,
                    class_name=track.class_name,
                    confidence=track.score,
                    bbox=track.bbox,
                )
                for track in tracks
            ),
        )
        try:
            self._requests.put_nowait(request)
            if self._metrics is not None:
                self._metrics.record_evidence("queued")
            return True
        except queue.Full:
            if self._metrics is not None:
                self._metrics.record_evidence("queue_full")
            log.error("evidence queue full; event %s will have no media", event.event_id)
            return False

    def _monitor_recorders(self) -> None:
        while not self._stop.is_set():
            desired = self._registry.snapshot()
            with self._recorders_lock:
                for stream_id, recorder in list(self._recorders.items()):
                    camera = desired.get(stream_id)
                    if (
                        camera is None
                        or camera.uri != recorder.camera.uri
                        or recorder.process.poll() is not None
                    ):
                        _terminate(recorder.process)
                        self._recorders.pop(stream_id, None)
                for stream_id, camera in desired.items():
                    if stream_id not in self._recorders:
                        try:
                            self._recorders[stream_id] = self._start_recorder(camera)
                        except Exception:
                            log.exception("cannot start evidence recorder for %s", stream_id)
                self._cleanup_segments()
            self._stop.wait(2)

    def _start_recorder(self, camera: Camera) -> _Recorder:
        directory = self._camera_directory(camera.stream_id)
        directory.mkdir(parents=True, exist_ok=True)
        command = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-y"]
        if camera.uri.lower().startswith(("rtsp://", "rtsps://")):
            command.extend(["-rtsp_transport", "tcp"])
        command.extend(
            [
                "-i",
                camera.uri,
                "-map",
                "0:v:0",
                "-an",
                "-c:v",
                "copy",
                "-f",
                "segment",
                "-segment_time",
                str(self._settings.evidence_segment_seconds),
                "-segment_atclocktime",
                "1",
                "-reset_timestamps",
                "1",
                "-strftime",
                "1",
                str(directory / "segment-%Y%m%dT%H%M%S.mp4"),
            ]
        )
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.info("evidence ring recorder started for %s", camera.stream_id)
        return _Recorder(camera=camera, directory=directory, process=process)

    def _cleanup_segments(self) -> None:
        cutoff = time.time() - self._settings.evidence_retention_seconds
        for recorder in self._recorders.values():
            for path in recorder.directory.glob("segment-*.mp4"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except FileNotFoundError:
                    continue
        work_dir = self._settings.evidence_dir / "work"
        for path in work_dir.glob("*"):
            try:
                if path.is_dir() and path.stat().st_mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
            except FileNotFoundError:
                continue

    def _camera_directory(self, stream_id: str) -> Path:
        digest = hashlib.sha256(stream_id.encode()).hexdigest()[:16]
        return self._settings.evidence_dir / f"camera-{digest}"

    def _run_worker(self) -> None:
        while not self._stop.is_set():
            try:
                request = self._requests.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._produce(request)
            except Exception:
                if self._metrics is not None:
                    self._metrics.record_evidence("failed")
                log.exception("evidence generation failed for event %s", request.event_id)
            finally:
                self._requests.task_done()

    def _produce(self, request: EvidenceRequest) -> None:
        ready_at = (
            request.timestamp
            + self._settings.evidence_post_seconds
            + self._settings.evidence_segment_seconds
        )
        if ready_at > time.time():
            self._stop.wait(ready_at - time.time())
        if self._stop.is_set():
            return
        event_dir = self._settings.evidence_dir / "work" / request.event_id
        event_dir.mkdir(parents=True, exist_ok=True)
        try:
            segments = self._segments_for_event(request)
            clip = self._build_clip(event_dir, segments, request) if segments else None
            snapshot = self._extract_snapshot(event_dir, clip, segments, request)
            if snapshot is None:
                snapshot = self._capture_fallback_snapshot(event_dir, request.camera)
            if snapshot is not None:
                self._annotate_snapshot(snapshot, request)
            if clip is not None and clip.stat().st_size > self._settings.evidence_max_clip_bytes:
                log.warning(
                    "clip for event %s exceeds %d bytes; uploading snapshot only",
                    request.event_id,
                    self._settings.evidence_max_clip_bytes,
                )
                if self._metrics is not None:
                    self._metrics.record_evidence("clip_oversize")
                clip = None
            if snapshot is None and clip is None:
                raise RuntimeError("no usable ring-buffer media")
            self._upload(request, snapshot, clip)
        finally:
            shutil.rmtree(event_dir, ignore_errors=True)

    def _segments_for_event(self, request: EvidenceRequest) -> list[Path]:
        directory = self._camera_directory(request.camera.stream_id)
        start = request.timestamp - self._settings.evidence_pre_seconds
        end = request.timestamp + self._settings.evidence_post_seconds
        margin = self._settings.evidence_segment_seconds * 2
        candidates: list[tuple[float, Path]] = []
        for path in directory.glob("segment-*.mp4"):
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            if stat.st_size > 0 and start - margin <= stat.st_mtime <= end + margin:
                candidates.append((stat.st_mtime, path))
        return [path for _mtime, path in sorted(candidates)]

    def _build_clip(
        self, event_dir: Path, segments: list[Path], request: EvidenceRequest
    ) -> Path | None:
        if not segments:
            return None
        concat = event_dir / "segments.txt"
        concat.write_text("".join(f"file '{path}'\n" for path in segments))
        output = event_dir / "evidence.mp4"
        estimated_first_start = (
            segments[0].stat().st_mtime - self._settings.evidence_segment_seconds
        )
        desired_start = request.timestamp - self._settings.evidence_pre_seconds
        trim_offset = max(0.0, desired_start - estimated_first_start)
        duration = self._settings.evidence_pre_seconds + self._settings.evidence_post_seconds
        input_args = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-ss",
            f"{trim_offset:.3f}",
            "-t",
            f"{duration:.3f}",
            "-an",
        ]
        encoders = [
            ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "24", "-b:v", "0"],
            ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"],
        ]
        for encoder in encoders:
            command = [
                *input_args,
                *encoder,
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-y",
                str(output),
            ]
            result = subprocess.run(command, capture_output=True, timeout=60, check=False)
            if result.returncode == 0 and output.is_file() and output.stat().st_size > 0:
                return output
            log.warning(
                "clip encoding with %s failed: %s",
                encoder[1],
                result.stderr.decode(errors="replace"),
            )
        return None

    def _extract_snapshot(
        self,
        event_dir: Path,
        clip: Path | None,
        segments: list[Path],
        request: EvidenceRequest,
    ) -> Path | None:
        source = clip
        seek = self._settings.evidence_pre_seconds
        if source is None and segments:
            source = min(segments, key=lambda path: abs(path.stat().st_mtime - request.timestamp))
            seek = 0.0
        if source is None:
            return None
        output = event_dir / "snapshot.jpg"
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            str(max(0.0, seek)),
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(output),
        ]
        result = subprocess.run(command, capture_output=True, timeout=30, check=False)
        if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            return None
        return output

    def _capture_fallback_snapshot(self, event_dir: Path, camera: Camera) -> Path | None:
        output = event_dir / "snapshot.jpg"
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
        if camera.uri.lower().startswith(("rtsp://", "rtsps://")):
            command.extend(["-rtsp_transport", "tcp"])
        command.extend(["-i", camera.uri, "-frames:v", "1", "-q:v", "2", "-y", str(output)])
        try:
            result = subprocess.run(command, capture_output=True, timeout=20, check=False)
        except subprocess.TimeoutExpired:
            return None
        return output if result.returncode == 0 and output.is_file() else None

    def _annotate_snapshot(self, path: Path, request: EvidenceRequest) -> None:
        with Image.open(path) as source:
            image = source.convert("RGB")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()
        scale_x = image.width / max(1, request.frame_width)
        scale_y = image.height / max(1, request.frame_height)
        line_width = max(2, round(image.width / 500))
        for box in request.boxes:
            x1, y1, x2, y2 = box.bbox
            rect = (x1 * scale_x, y1 * scale_y, x2 * scale_x, y2 * scale_y)
            target = box.object_id == request.object_id
            color = "#ff3b30" if target else "#22c55e"
            draw.rectangle(rect, outline=color, width=line_width * (2 if target else 1))
            label = f"{box.class_name} #{box.object_id} {box.confidence:.2f}"
            bounds = draw.textbbox((rect[0], rect[1]), label, font=font)
            draw.rectangle(bounds, fill=color)
            draw.text((rect[0], rect[1]), label, fill="white", font=font)
        header = (
            f"{request.event_type} | {request.rule_id} | "
            f"{datetime.fromtimestamp(request.timestamp, tz=UTC).isoformat()}"
        )
        header_bounds = draw.textbbox((8, 8), header, font=font)
        draw.rounded_rectangle(
            (
                header_bounds[0] - 4,
                header_bounds[1] - 4,
                header_bounds[2] + 4,
                header_bounds[3] + 4,
            ),
            radius=3,
            fill="#111827",
        )
        draw.text((8, 8), header, fill="white", font=font)
        image.save(path, "JPEG", quality=90, optimize=True)

    def _upload(self, request: EvidenceRequest, snapshot: Path | None, clip: Path | None) -> None:
        url = f"{self._settings.api_url}/api/v1/events/{request.event_id}/evidence"
        headers = (
            {"Authorization": f"Bearer {self._settings.ingest_token}"}
            if self._settings.ingest_token
            else {}
        )
        delay = 1.0
        for attempt in range(5):
            files: dict[str, tuple[str, bytes, str]] = {}
            if snapshot is not None:
                files["snapshot"] = ("snapshot.jpg", snapshot.read_bytes(), "image/jpeg")
            if clip is not None:
                files["clip"] = ("clip.mp4", clip.read_bytes(), "video/mp4")
            try:
                response = httpx.post(url, headers=headers, files=files, timeout=90)
                if response.status_code == 404 and attempt < 4:
                    self._stop.wait(delay)
                    delay *= 2
                    continue
                response.raise_for_status()
                if self._metrics is not None:
                    self._metrics.record_evidence("uploaded")
                log.info("event evidence uploaded: %s", request.event_id)
                return
            except Exception:
                if attempt == 4:
                    raise
                self._stop.wait(delay)
                delay *= 2


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
