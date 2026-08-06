from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import cv2
import numpy as np

from ..types import Frame
from .base import FrameSource


class FileSource(FrameSource):
    """Loops a video file; useful for benchmarks and integration tests."""

    def __init__(self, camera_id: str, path: str, target_fps: int = 15) -> None:
        self.camera_id = camera_id
        self.path = path
        self.frame_interval = 1.0 / max(target_fps, 1)
        self._stop = threading.Event()

    def frames(self) -> Iterator[Frame]:
        seq = 0
        while not self._stop.is_set():
            cap = cv2.VideoCapture(self.path)
            if not cap.isOpened():
                raise RuntimeError(f"cannot open video file: {self.path}")
            while not self._stop.is_set():
                ok, img = cap.read()
                if not ok:
                    break
                time.sleep(self.frame_interval)
                seq += 1
                yield Frame(camera_id=self.camera_id, seq=seq, image=img)
            cap.release()

    def stop(self) -> None:
        self._stop.set()


class SyntheticSource(FrameSource):
    """Generates frames with moving rectangles; no camera or file needed."""

    def __init__(
        self,
        camera_id: str,
        width: int = 1280,
        height: int = 720,
        n_objects: int = 4,
        target_fps: int = 15,
        max_frames: int | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self.n_objects = n_objects
        self.frame_interval = 1.0 / max(target_fps, 1)
        self.max_frames = max_frames
        self._stop = threading.Event()

    def frames(self) -> Iterator[Frame]:
        seq = 0
        rng = np.random.default_rng(42)
        velocities = rng.uniform(2, 8, size=self.n_objects)
        while not self._stop.is_set():
            if self.max_frames is not None and seq >= self.max_frames:
                return
            img = np.full((self.height, self.width, 3), 32, dtype=np.uint8)
            for i in range(self.n_objects):
                x = int((i * self.width // self.n_objects + velocities[i] * seq * 3) % (self.width - 120))
                y = min(80 + i * 150, self.height - 80)
                cv2.rectangle(img, (x, y), (x + 100, y + 60), (80, 160, 220), -1)
            time.sleep(self.frame_interval)
            seq += 1
            yield Frame(camera_id=self.camera_id, seq=seq, image=img)

    def stop(self) -> None:
        self._stop.set()
