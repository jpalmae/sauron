from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections import deque

import numpy as np

from .config import AudioConfig
from .rules.events import Event, EventType, Priority

log = logging.getLogger(__name__)


class PeakDetector:
    """RMS peak detector over a rolling baseline."""

    def __init__(self, peak_factor: float = 4.0, window: int = 50) -> None:
        self.peak_factor = peak_factor
        self._window: deque[float] = deque(maxlen=window)
        self._last_alert = 0.0
        self.cooldown_s = 20.0

    def feed(self, pcm: np.ndarray) -> float | None:
        """Feed int16 PCM chunk; returns RMS when it's an anomaly, else None."""
        if pcm.size == 0:
            return None
        rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
        baseline = float(np.mean(self._window)) if self._window else 0.0
        self._window.append(rms)
        now = time.monotonic()
        if (
            baseline > 1.0
            and rms > baseline * self.peak_factor
            and now - self._last_alert > self.cooldown_s
        ):
            self._last_alert = now
            return rms
        return None


class AudioTap:
    """ffmpeg -> PCM s16le mono; peaks become AUDIO_ANOMALY events."""

    def __init__(self, camera_id: str, source: str, cfg: AudioConfig, on_event) -> None:
        self.camera_id = camera_id
        self.source = source
        self.cfg = cfg
        self.on_event = on_event
        self.detector = PeakDetector(cfg.peak_factor)
        self.detector.cooldown_s = cfg.cooldown_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"audio-{camera_id}", daemon=True)

    def _run(self) -> None:
        chunk_bytes = self.cfg.sample_rate * 2  # 1 second of s16 mono
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", self.source,
            "-vn", "-ac", "1", "-ar", str(self.cfg.sample_rate),
            "-f", "s16le", "pipe:1",
        ]
        while not self._stop.is_set():
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                assert proc.stdout is not None
                while not self._stop.is_set():
                    data = proc.stdout.read(chunk_bytes)
                    if not data:
                        break
                    rms = self.detector.feed(np.frombuffer(data, dtype=np.int16))
                    if rms is not None:
                        log.warning("[%s] AUDIO_ANOMALY rms=%.0f", self.camera_id, rms)
                        self.on_event(
                            Event(
                                event_type=EventType.AUDIO_ANOMALY,
                                camera_id=self.camera_id,
                                timestamp=time.time(),
                                confidence=1.0,
                                priority=Priority.WARNING,
                                rule_id="audio-peak",
                                metadata={"rms": round(rms, 1)},
                            )
                        )
                proc.kill()
            except Exception:
                log.exception("[%s] audio tap crashed; retrying", self.camera_id)
            self._stop.wait(5.0)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
