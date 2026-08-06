from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator

import cv2

from ..config import CaptureConfig
from ..types import Frame
from .base import FrameSource

log = logging.getLogger(__name__)

NVVDEC_PIPELINE = (
    "rtspsrc location={url} latency={latency} protocols=tcp ! "
    "rtph264depay ! h264parse ! nvv4l2decoder ! "
    "nvvidconv ! video/x-raw,format=BGRx ! "
    "videoconvert ! video/x-raw,format=BGR ! "
    "appsink drop=true max-buffers=2 sync=false"
)


def build_gst_pipeline(url: str, latency_ms: int, decoder: str = "nvv4l2decoder") -> str:
    return NVVDEC_PIPELINE.format(url=url, latency=latency_ms).replace(
        "nvv4l2decoder", decoder, 1
    )


class RTSPSource(FrameSource):
    """RTSP capture via OpenCV/GStreamer with NVDEC decode and auto-reconnect.

    Falls back to plain FFmpeg-based cv2.VideoCapture when GStreamer is
    unavailable (e.g. local dev on non-GPU machines).
    """

    def __init__(
        self,
        camera_id: str,
        url: str,
        cfg: CaptureConfig | None = None,
        use_gstreamer: bool = True,
        decoder: str = "nvv4l2decoder",
        target_fps: int = 15,
    ) -> None:
        self.camera_id = camera_id
        self.url = url
        self.cfg = cfg or CaptureConfig()
        self.use_gstreamer = use_gstreamer
        self.decoder = decoder
        self.frame_interval = 1.0 / max(target_fps, 1)
        self._stop = threading.Event()

    def _open(self) -> cv2.VideoCapture | None:
        cap: cv2.VideoCapture | None = None
        if self.use_gstreamer:
            pipeline = build_gst_pipeline(self.url, self.cfg.latency_ms, self.decoder)
            cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
            if not cap.isOpened():
                log.warning("[%s] GStreamer open failed, falling back to FFmpeg", self.camera_id)
                cap.release()
                cap = None
        if cap is None:
            cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        return cap if cap.isOpened() else None

    def frames(self) -> Iterator[Frame]:
        seq = 0
        failures = 0
        last_emit = 0.0
        while not self._stop.is_set():
            cap = self._open()
            if cap is None:
                failures += 1
                backoff = min(self.cfg.reconnect_backoff_s * failures, 30.0)
                log.warning("[%s] connect failed, retrying in %.1fs", self.camera_id, backoff)
                self._stop.wait(backoff)
                continue
            failures = 0
            log.info("[%s] stream connected", self.camera_id)

            while not self._stop.is_set():
                ok, img = cap.read()
                if not ok or img is None:
                    log.warning("[%s] frame read failed, reconnecting", self.camera_id)
                    break
                now = time.monotonic()
                if now - last_emit < self.frame_interval:
                    continue
                last_emit = now
                seq += 1
                yield Frame(camera_id=self.camera_id, seq=seq, image=img)
            cap.release()

    def stop(self) -> None:
        self._stop.set()
