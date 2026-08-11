from __future__ import annotations

import json
import logging

from ..rules.occupancy import classify_posture
from ..types import Frame, TrackedObject

log = logging.getLogger(__name__)

KEY_PREFIX = "sauron:detections:"
TTL_S = 5


class RedisDetectionsPublisher:
    """Publishes the latest frame's detections per camera to a Redis key.

    Key ``sauron:detections:{camera_id}`` holds a short JSON snapshot (boxes
    normalized to [0,1], posture and keypoints) so the dashboard can draw a
    live overlay on top of the video tile. Overwritten every frame, TTL 5s.
    """

    def __init__(self, redis_url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(redis_url)

    def __call__(
        self, camera_id: str, frame: Frame, tracks: list[TrackedObject]
    ) -> None:
        try:
            h, w = frame.image.shape[:2]
            objs: list[dict] = []
            for t in tracks:
                x1, y1, x2, y2 = t.bbox
                obj = {
                    "id": int(t.object_id),
                    "class": t.class_name,
                    "box": [x1 / w, y1 / h, x2 / w, y2 / h],
                }
                if t.class_name == "person" and t.keypoints is not None:
                    obj["posture"] = classify_posture(t.keypoints, t.bbox)
                    obj["keypoints"] = [
                        [float(t.keypoints[i][0]) / w, float(t.keypoints[i][1]) / h]
                        for i in range(len(t.keypoints))
                    ]
                objs.append(obj)
            payload = {
                "ts": frame.timestamp,
                "width": int(w),
                "height": int(h),
                "objects": objs,
            }
            self._client.set(f"{KEY_PREFIX}{camera_id}", json.dumps(payload), ex=TTL_S)
        except Exception:
            log.exception("failed to publish detections")
