from __future__ import annotations

import base64
import logging
import re
import shutil
from abc import ABC, abstractmethod

import cv2
import numpy as np

log = logging.getLogger(__name__)

_PLATE_RE = re.compile(r"[A-Z0-9]{4,9}")


def normalize_plate(text: str) -> str:
    """Best plate candidate from raw OCR text; '' when nothing plausible.

    Splits into alnum tokens and returns the longest 4-9 char token
    (plate-shaped), favoring tokens containing digits.
    """
    tokens = re.findall(r"[A-Za-z0-9]+", text.upper())
    plausible = [t for t in tokens if 4 <= len(t) <= 9]
    if not plausible:
        # fallback: single long blob (common OCR smearing)
        blob = re.sub(r"[^A-Z0-9]", "", text.upper())
        m = _PLATE_RE.search(blob)
        return m.group(0) if m else ""
    with_digits = [t for t in plausible if any(c.isdigit() for c in t)]
    return max(with_digits or plausible, key=len)


class OcrBackend(ABC):
    @abstractmethod
    def read_plate(self, crop: np.ndarray) -> tuple[str, float]:
        """Returns (normalized plate text, confidence 0..1); ('', 0) on failure."""


class TesseractOcr(OcrBackend):
    """Local OCR via pytesseract (needs the tesseract binary in the image)."""

    def __init__(self) -> None:
        self._available = shutil.which("tesseract") is not None
        if not self._available:
            log.warning("tesseract binary not found; ALPR OCR disabled")

    def read_plate(self, crop: np.ndarray) -> tuple[str, float]:
        if not self._available or crop.size == 0:
            return "", 0.0
        import pytesseract

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        data = pytesseract.image_to_data(
            gray,
            config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            output_type=pytesseract.Output.DICT,
        )
        texts = [t for t in data["text"] if t.strip()]
        if not texts:
            return "", 0.0
        confs = [float(c) for c, t in zip(data["conf"], data["text"]) if t.strip() and float(c) > 0]
        plate = normalize_plate("".join(texts))
        if not plate:
            return "", 0.0
        return plate, (sum(confs) / len(confs) / 100.0) if confs else 0.4


class VlmOcr(OcrBackend):
    """OCR via an OpenAI-compatible vision endpoint (crop -> plate text)."""

    def __init__(self, base_url: str, model: str, api_key: str = "", timeout_s: float = 15.0) -> None:
        import httpx

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(base_url=base_url, headers=headers, timeout=timeout_s)
        self._model = model

    def read_plate(self, crop: np.ndarray) -> tuple[str, float]:
        if crop.size == 0:
            return "", 0.0
        ok, jpeg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            return "", 0.0
        b64 = base64.b64encode(jpeg.tobytes()).decode()
        try:
            resp = self._client.post(
                "/chat/completions",
                json={
                    "model": self._model,
                    "temperature": 0,
                    "max_tokens": 20,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Read the license plate text. Reply with ONLY the plate characters, or 'NONE' if unreadable.",
                                },
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                            ],
                        }
                    ],
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:  # noqa: BLE001 - network/parse issues disable this read
            log.debug("vlm ocr failed: %s", e)
            return "", 0.0
        if text.upper().startswith("NONE"):
            return "", 0.0
        plate = normalize_plate(text)
        return (plate, 0.85) if plate else ("", 0.0)


def build_ocr(backend: str, **kwargs) -> OcrBackend:
    if backend == "vlm":
        return VlmOcr(
            kwargs["base_url"], kwargs.get("model", ""), kwargs.get("api_key", "")
        )
    return TesseractOcr()
