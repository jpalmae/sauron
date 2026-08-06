from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import numpy as np


class EventType(StrEnum):
    LINE_CROSSING = "LINE_CROSSING"
    STOPPED_VEHICLE = "STOPPED_VEHICLE"
    OBSTRUCTION = "OBSTRUCTION"
    WRONG_WAY = "WRONG_WAY"
    CONGESTION = "CONGESTION"


class Priority(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Event:
    event_type: EventType
    camera_id: str
    timestamp: float
    confidence: float
    priority: Priority
    rule_id: str
    object_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    snapshot: np.ndarray | None = None
    clip: bytes | None = None  # pre-event MP4 evidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": str(self.event_type),
            "camera_id": self.camera_id,
            "timestamp": self.timestamp,
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(self.timestamp)),
            "confidence": round(self.confidence, 4),
            "priority": str(self.priority),
            "rule_id": self.rule_id,
            "object_id": self.object_id,
            "metadata": self.metadata,
            "has_snapshot": self.snapshot is not None,
            "has_clip": self.clip is not None,
        }
