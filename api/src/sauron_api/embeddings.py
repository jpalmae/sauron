from __future__ import annotations

import io
import logging
import math
from pathlib import Path

import numpy as np

from .config import get_settings

log = logging.getLogger(__name__)

_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
_BOS, _EOS, _CTX = 49406, 49407, 77


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    return vec / (np.linalg.norm(vec, axis=-1, keepdims=True) + 1e-10)


class ClipEmbeddings:
    """CLIP ViT-B/32 via ONNX Runtime (CPU). Lazy-loads on first use.

    Disabled gracefully when the model files are absent: embed_* return None
    and /search reports 503.
    """

    def __init__(self, models_dir: str = "models") -> None:
        self._dir = Path(models_dir)
        self._visual = None
        self._text = None
        self._tokenizer = None
        self._checked = False
        self.available = False

    def _load(self) -> None:
        if self._checked:
            return
        self._checked = True
        visual = self._dir / "clip_visual.onnx"
        text = self._dir / "clip_text.onnx"
        tok = self._dir / "clip_tokenizer" / "tokenizer.json"
        if not (visual.exists() and text.exists() and tok.exists()):
            log.warning("CLIP models not found in %s; semantic search disabled", self._dir)
            return
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2
            self._visual = ort.InferenceSession(str(visual), opts, providers=["CPUExecutionProvider"])
            self._text = ort.InferenceSession(str(text), opts, providers=["CPUExecutionProvider"])
            self._tokenizer = Tokenizer.from_file(str(tok))  # type: ignore[assignment]
            self.available = True
            log.info("CLIP embeddings ready (%s)", self._dir)
        except Exception:
            log.exception("failed to load CLIP models")

    def embed_image(self, jpeg: bytes) -> list[float] | None:
        self._load()
        if not self.available or self._visual is None:
            return None
        from PIL import Image

        img = Image.open(io.BytesIO(jpeg)).convert("RGB").resize((224, 224), Image.Resampling.BICUBIC)
        arr = np.asarray(img, dtype=np.float32) / 255.0
        arr = (arr - _MEAN) / _STD
        arr = arr.transpose(2, 0, 1)[None].astype(np.float32)
        out = self._visual.run(["embedding"], {"pixel_values": arr})[0]  # type: ignore[union-attr]
        return _l2_normalize(out)[0].astype(np.float64).tolist()

    def embed_text(self, query: str) -> list[float] | None:
        self._load()
        if not self.available or self._text is None or self._tokenizer is None:
            return None
        enc = self._tokenizer.encode(query)  # type: ignore[union-attr]
        ids = [_BOS, *enc.ids[: _CTX - 2], _EOS]
        mask = [1] * len(ids)
        ids = ids + [0] * (_CTX - len(ids))
        mask = mask + [0] * (_CTX - len(mask))
        out = self._text.run(  # type: ignore[union-attr]
            ["embedding"],
            {
                "input_ids": np.array([ids], dtype=np.int64),
                "attention_mask": np.array([mask], dtype=np.int64),
            },
        )[0]
        return _l2_normalize(out)[0].astype(np.float64).tolist()


_embeddings: ClipEmbeddings | None = None


def get_embeddings() -> ClipEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = ClipEmbeddings(get_settings().clip_models_dir)
    return _embeddings


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity (sqlite/python fallback path)."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-10
    nb = math.sqrt(sum(x * x for x in b)) or 1e-10
    return dot / (na * nb)
