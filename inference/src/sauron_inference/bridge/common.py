from __future__ import annotations

import base64
import json
import logging
from typing import Any

import cv2

from ..rules.events import Event

log = logging.getLogger(__name__)


def event_payload(event: Event, jpeg_quality: int = 80) -> dict[str, Any]:
    """Serializable event payload; snapshot encoded as base64 JPEG."""
    payload = event.to_dict()
    if event.snapshot is not None:
        ok, jpeg = cv2.imencode(".jpg", event.snapshot, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        if ok:
            payload["snapshot_jpeg"] = base64.b64encode(jpeg.tobytes()).decode()
    return payload


def dumps(event: Event) -> str:
    return json.dumps(event_payload(event))
