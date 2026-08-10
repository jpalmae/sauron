from __future__ import annotations

import io
import logging
from datetime import datetime

from PIL import Image, ImageDraw

log = logging.getLogger(__name__)

CELL_W, CELL_H = 320, 200
COLS = 6
_PADDING = 6
_LABEL_H = 18
_BG = (14, 18, 17)
_INK = (220, 230, 226)


def build_contact_sheet(
    items: list[tuple[bytes, str]], cols: int = COLS
) -> bytes:
    """items: [(jpeg_bytes, label)] → montage JPEG (B/W-safe with empty list)."""
    if not items:
        img = Image.new("RGB", (CELL_W, CELL_H), _BG)
        d = ImageDraw.Draw(img)
        d.text((12, 12), "sin evidencia en el rango", fill=_INK)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        return buf.getvalue()

    cols = min(cols, len(items))
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new(
        "RGB",
        (cols * (CELL_W + _PADDING) + _PADDING, rows * (CELL_H + _LABEL_H + _PADDING) + _PADDING),
        _BG,
    )
    draw = ImageDraw.Draw(sheet)
    for i, (jpeg, label) in enumerate(items):
        col, row = i % cols, i // cols
        x = _PADDING + col * (CELL_W + _PADDING)
        y = _PADDING + row * (CELL_H + _LABEL_H + _PADDING)
        try:
            thumb = Image.open(io.BytesIO(jpeg)).convert("RGB")
            thumb.thumbnail((CELL_W, CELL_H))
            ox = x + (CELL_W - thumb.width) // 2
            sheet.paste(thumb, (ox, y))
        except Exception:
            log.debug("bad snapshot in contact sheet", exc_info=True)
        draw.text((x + 2, y + CELL_H + 2), label[:40], fill=_INK)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def fmt_label(ts: datetime, event_type: str) -> str:
    return f"{ts:%m-%d %H:%M} {event_type}"
