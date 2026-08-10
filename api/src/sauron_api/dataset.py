from __future__ import annotations

import io
import zipfile


def yolo_label(class_id: int, bbox: list[float], img_w: int, img_h: int) -> str:
    """YOLO label line from xyxy pixel bbox."""
    x1, y1, x2, y2 = bbox
    cx = (x1 + x2) / 2 / img_w
    cy = (y1 + y2) / 2 / img_h
    w = (x2 - x1) / img_w
    h = (y2 - y1) / img_h
    return f"{class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def build_dataset_zip(
    items: list[tuple[bytes, str]],
) -> bytes:
    """items: [(jpeg_bytes, label_text)] -> YOLO dataset zip (images + labels)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (jpeg, label) in enumerate(items):
            name = f"img_{i:05d}"
            zf.writestr(f"images/{name}.jpg", jpeg)
            zf.writestr(f"labels/{name}.txt", label)
        zf.writestr(
            "dataset.yaml",
            "names:\n  0: car\n  1: motorcycle\n  2: bus\n  3: truck\n  4: person\n",
        )
    return buf.getvalue()
