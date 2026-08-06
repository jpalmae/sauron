from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..config import ThresholdsConfig
from ..types import Frame, TrackedObject
from .events import Event
from .speed import SpeedEstimator


@dataclass
class RuleContext:
    camera_id: str
    fps: int
    thresholds: ThresholdsConfig
    speed_estimator: SpeedEstimator | None = None


class Rule(ABC):
    rule_id: str
    _stale_after_s = 60.0

    @abstractmethod
    def process(
        self, frame: Frame, tracks: list[TrackedObject], ctx: RuleContext
    ) -> list[Event]: ...

    def _purge(self, last_seen: dict[int, float], now: float) -> None:
        stale = [oid for oid, ts in last_seen.items() if now - ts > self._stale_after_s]
        for oid in stale:
            del last_seen[oid]
            self._drop_object(oid)

    def _drop_object(self, object_id: int) -> None:
        """Remove per-object state when a track disappears."""
