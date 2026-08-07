#!/usr/bin/env python3
"""Ensure model artifacts for the active config exist before starting.

- Copies baked ONNX files (from /app/models-baked) into the models volume.
- Builds missing TensorRT engines on the GPU host (FP16; INT8 via flag).

Usage: python tools/ensure_models.py -c configs/pipeline.yaml [--int8]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "src")

from sauron_inference.config import load_config
from sauron_inference.models import CATALOG

BAKED_DIR = Path("/app/models-baked")


def models_in_use(config_path: str) -> set[str]:
    cfg = load_config(config_path)
    return {s.resolved_model(cfg.defaults) for s in cfg.streams} or {cfg.defaults.model}


def copy_baked(models_dir: Path) -> None:
    if not BAKED_DIR.is_dir():
        return
    models_dir.mkdir(parents=True, exist_ok=True)
    for onnx in BAKED_DIR.glob("*.onnx"):
        dst = models_dir / onnx.name
        if not dst.exists():
            shutil.copy2(onnx, dst)
            print(f"baked model -> {dst}")


def ensure_engines(models_dir: Path, names: set[str], int8: bool, calib_data: str | None) -> None:
    from tools.build_engine import build_engine  # type: ignore[import-not-found]

    for name in sorted(names):
        info = CATALOG[name]
        engine = models_dir / info.engine_file
        onnx = models_dir / info.onnx_file
        if engine.exists():
            continue
        if not onnx.exists():
            raise SystemExit(f"missing ONNX for {name}: {onnx} (image should bake it)")
        print(f"building {engine.name} from {onnx.name} (first boot, takes a few minutes)…")
        build_engine(
            onnx, engine, fp16=not int8, int8=int8, workspace_gb=4,
            calib_data=calib_data, imgsz=640,
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="configs/pipeline.yaml")
    ap.add_argument("--models-dir", default="models")
    ap.add_argument("--int8", action="store_true")
    ap.add_argument("--calib-data", default=None)
    args = ap.parse_args()

    models_dir = Path(args.models_dir)
    names = models_in_use(args.config)
    print(f"models in use: {sorted(names)}")
    copy_baked(models_dir)
    ensure_engines(models_dir, names, args.int8, args.calib_data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
