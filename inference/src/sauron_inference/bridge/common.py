from __future__ import annotations

import base64
import json
import logging
from typing import Any

import cv2

from ..rules.events import Event

log = logging.getLogger(__name__)


def event_payload(event: Event, jpeg_quality: int = 80) -> dict[str, Any]:
    """Serializable event payload; snapshot/clip encoded as base64."""
    payload = event.to_dict()
    if event.snapshot is not None:
        ok, jpeg = cv2.imencode(".jpg", event.snapshot, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        if ok:
            payload["snapshot_jpeg"] = base64.b64encode(jpeg.tobytes()).decode()
    if event.clip is not None:
        payload["clip_mp4"] = base64.b64encode(event.clip).decode()
    return payload


def dumps(event: Event) -> str:
    return json.dumps(event_payload(event))
