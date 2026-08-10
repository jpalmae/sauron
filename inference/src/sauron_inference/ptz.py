from __future__ import annotations

import logging
import threading
import time

from .config import PTZConfig

log = logging.getLogger(__name__)

# how strongly to steer toward the target (fraction of frame half -> velocity)
_GAIN = 1.2
_DEADBAND = 0.08


def compute_move(
    centroid: tuple[float, float], frame_size: tuple[int, int]
) -> tuple[float, float]:
    """Pan/tilt velocity (x, y in [-1, 1]) to center the object centroid."""
    w, h = frame_size
    dx = (centroid[0] - w / 2) / (w / 2)
    dy = (centroid[1] - h / 2) / (h / 2)
    vx = 0.0 if abs(dx) < _DEADBAND else max(-1.0, min(1.0, dx * _GAIN))
    vy = 0.0 if abs(dy) < _DEADBAND else max(-1.0, min(1.0, -dy * _GAIN))
    return vx, vy


class PtzController:
    """ONVIF PTZ autotracking: follow the object of a critical event for
    follow_seconds, then return to the configured preset. Rate-limited."""

    def __init__(self, cfg: PTZConfig) -> None:
        self.cfg = cfg
        self._service = None
        self._lock = threading.Lock()
        self._busy_until = 0.0
        self._timer: threading.Timer | None = None

    def _connect(self):
        if self._service is None:
            from onvif import ONVIFCamera

            cam = ONVIFCamera(
                self.cfg.host, self.cfg.port, self.cfg.username, self.cfg.password
            )
            self._service = cam.create_ptz_service()
        return self._service

    def _move(self, vx: float, vy: float) -> None:
        self._connect().ContinuousMove(
            {"Velocity": {"PanTilt": {"x": vx, "y": vy}, "Zoom": {"x": 0.0}}}
        )

    def _stop(self) -> None:
        try:
            self._connect().Stop({"PanTilt": True, "Zoom": True})
        except Exception:
            log.warning("ptz stop failed", exc_info=True)

    def _home(self) -> None:
        self._stop()
        if self.cfg.preset_token:
            try:
                self._connect().GotoPreset({"PresetToken": self.cfg.preset_token})
            except Exception:
                log.warning("ptz goto preset failed", exc_info=True)

    def track(
        self,
        centroid: tuple[float, float],
        frame_size: tuple[int, int],
    ) -> bool:
        """Steer toward the target. Returns False when busy (cooldown)."""
        with self._lock:
            now = time.monotonic()
            if now < self._busy_until:
                return False
            self._busy_until = now + self.cfg.cooldown_s
        vx, vy = compute_move(centroid, frame_size)
        try:
            self._move(vx, vy)
        except Exception:
            log.warning("ptz move failed", exc_info=True)
            return False
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self.cfg.follow_seconds, self._home)
        self._timer.daemon = True
        self._timer.start()
        log.info("ptz tracking (vx=%.2f vy=%.2f) for %.0fs", vx, vy, self.cfg.follow_seconds)
        return True
