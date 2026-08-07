#!/usr/bin/env python3
"""Export the full model catalog to ONNX (requires ultralytics + torch).

Used by CI before baking images and for local model refresh:
    python tools/export_models.py [--models-dir models]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "src")

from sauron_inference.models import CATALOG


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", default="models")
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args()

    from ultralytics import YOLO

    out_dir = Path(args.models_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, info in CATALOG.items():
        dst = out_dir / info.onnx_file
        if dst.exists():
            print(f"skip {name} (exists)")
            continue
        model = YOLO(f"{name}.pt")
        model.export(format="onnx", imgsz=args.imgsz, simplify=True, opset=12, dynamic=False)
        Path(f"{name}.onnx").rename(dst)
        Path(f"{name}.pt").unlink(missing_ok=True)
        print(f"exported {dst} ({dst.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
