from __future__ import annotations

import base64
import json
import logging
import os

import cv2
import httpx
import numpy as np

from ..config import OpenAIDetectorConfig
from ..types import Detection
from .base import Detector

log = logging.getLogger(__name__)

PROMPT = """Detect all vehicles in this traffic camera image.
Return ONLY a JSON array, no prose, no code fences. Each element:
{"class": "car"|"bus"|"truck"|"motorcycle", "bbox": [x1, y1, x2, y2], "confidence": 0..1}
Coordinates normalized to [0, 1] relative to image width/height.
If no vehicles are visible, return []."""


def parse_detections(
    content: str,
    orig_shape: tuple[int, int],
    classes: dict[int, str],
    conf_threshold: float,
) -> list[Detection]:
    """Parse the model's JSON answer into pixel-space Detections."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json")
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        log.warning("openai detector: no JSON array in response")
        return []
    try:
        items = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        log.warning("openai detector: invalid JSON response")
        return []
    if not isinstance(items, list):
        return []

    h, w = orig_shape
    valid_names = {v: k for k, v in classes.items()}
    detections: list[Detection] = []
    for item in items:
        try:
            name = str(item["class"]).lower().strip()
            box = [float(v) for v in item["bbox"]]
            score = float(item.get("confidence", 0.9))
        except (KeyError, TypeError, ValueError):
            continue
        if name not in valid_names or len(box) != 4 or score < conf_threshold:
            continue
        x1, y1, x2, y2 = box
        if max(box) <= 1.5:  # normalized coordinates
            x1, x2 = x1 * w, x2 * w
            y1, y2 = y1 * h, y2 * h
        x1, y1 = max(0.0, x1), max(0.0, y1)
        x2, y2 = min(float(w - 1), x2), min(float(h - 1), y2)
        if x2 <= x1 or y2 <= y1:
            continue
        detections.append(
            Detection(
                bbox=np.array([x1, y1, x2, y2], dtype=np.float32),
                score=score,
                class_id=valid_names[name],
                class_name=name,
            )
        )
    return detections


class OpenAICompatDetector(Detector):
    """Runs detection against an OpenAI-compatible vision API (local or remote).

    Uses POST {base_url}/chat/completions with a base64 JPEG. Note that remote
    VLM inference is much slower than local TensorRT; use it for low-FPS
    monitoring, GPU-less deployments, or as a fallback backend.
    """

    def __init__(
        self,
        cfg: OpenAIDetectorConfig,
        classes: dict[int, str] | None = None,
        conf_threshold: float = 0.5,
        client: httpx.Client | None = None,
    ) -> None:
        self.cfg = cfg
        self.classes = classes or {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
        self.conf_threshold = conf_threshold
        if client is not None:
            self._client = client
        else:
            api_key = os.environ.get(cfg.api_key_env, "")
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            self._client = httpx.Client(
                base_url=cfg.base_url, headers=headers, timeout=cfg.timeout_s
            )

    def detect(self, image: np.ndarray) -> list[Detection]:
        h, w = image.shape[:2]
        scale = self.cfg.max_image_side / max(h, w)
        if scale < 1.0:
            image = cv2.resize(image, (int(w * scale), int(h * scale)))
        ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return []
        b64 = base64.b64encode(jpeg.tobytes()).decode()
        payload = {
            "model": self.cfg.model,
            "temperature": 0,
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
        }
        try:
            resp = self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as e:
            log.warning("openai detector request failed: %s", e)
            return []
        return parse_detections(content, (h, w), self.classes, self.conf_threshold)

    def close(self) -> None:
        self._client.close()
