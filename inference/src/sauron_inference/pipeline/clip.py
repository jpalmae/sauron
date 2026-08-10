from __future__ import annotations

import logging
import os
import tempfile
from collections import deque

import cv2
import numpy as np

from ..config import PrivacyConfig
from ..types import Frame, TrackedObject

log = logging.getLogger(__name__)


class ClipBuffer:
    """Rolling buffer of JPEG-encoded frames; renders pre-event MP4 evidence.

    JPEG storage keeps memory bounded (~80 KB/frame instead of ~2.7 MB raw):
    8 s at 15 fps ≈ 10 MB per stream.
    """

    def __init__(
        self,
        preroll_seconds: float = 8.0,
        fps: int = 15,
        jpeg_quality: int = 75,
        clip_fps: int = 12,
    ) -> None:
        self._frames: deque[tuple[float, bytes]] = deque(
            maxlen=max(1, int(preroll_seconds * fps))
        )
        self._quality = jpeg_quality
        self.clip_fps = clip_fps

    def add(
        self,
        frame: Frame,
        tracks: list[TrackedObject] | None = None,
        privacy: PrivacyConfig | None = None,
    ) -> None:
        image = frame.image
        if privacy is not None and tracks:
            from ..rules.privacy import redact_frame

            image = redact_frame(image, tracks, privacy)
        ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self._quality])
        if ok:
            self._frames.append((frame.timestamp, jpeg.tobytes()))

    def render_mp4(self) -> bytes | None:
        if len(self._frames) < 2:
            return None
        images: list[np.ndarray] = []
        for _, jpeg in self._frames:
            img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                images.append(img)
        if len(images) < 2:
            return None
        h, w = images[0].shape[:2]
        path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                path = tmp.name
            writer = cv2.VideoWriter(path, cv2.VideoWriter.fourcc(*"mp4v"), self.clip_fps, (w, h))
            if not writer.isOpened():
                log.warning("clip writer unavailable (mp4v codec)")
                return None
            for img in images:
                if img.shape[:2] != (h, w):
                    img = cv2.resize(img, (w, h))
                writer.write(img)
            writer.release()
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            log.exception("clip render failed")
            return None
        finally:
            if path and os.path.exists(path):
                os.unlink(path)
