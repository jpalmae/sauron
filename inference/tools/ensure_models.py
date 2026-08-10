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
    names = {s.resolved_model(cfg.defaults) for s in cfg.streams} or {cfg.defaults.model}
    # also need pose models for streams that use pose backends
    for s in cfg.streams:
        det = s.resolved_detector(cfg.defaults)
        if det.backend in ("pose", "pose_objects"):
            # pose_onnx_path is like models/yolov8n-pose.onnx -> catalog name yolov8n-pose
            pose_name = Path(s.resolved_pose_onnx(cfg.defaults)).stem
            if pose_name in CATALOG:
                names.add(pose_name)
    # default pose model if any stream uses pose
    if any(s.resolved_detector(cfg.defaults).backend in ("pose", "pose_objects") for s in cfg.streams) or cfg.defaults.detector.backend in ("pose", "pose_objects"):
        pose_default = Path(cfg.defaults.pose_onnx_path).stem
        if pose_default in CATALOG:
            names.add(pose_default)
    return names


def copy_baked(models_dir: Path) -> None:
    if not BAKED_DIR.is_dir():
        return
    try:
        models_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"warning: cannot create {models_dir}: {e}", file=sys.stderr)
        return
    for onnx in BAKED_DIR.glob("*.onnx"):
        dst = models_dir / onnx.name
        if not dst.exists():
            try:
                shutil.copy2(onnx, dst)
                print(f"baked model -> {dst}")
            except OSError as e:
                print(f"warning: cannot copy {onnx.name} to {dst}: {e} (using baked path)", file=sys.stderr)


def ensure_engines(models_dir: Path, names: set[str], int8: bool, calib_data: str | None) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_engine", Path(__file__).with_name("build_engine.py")
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    build_engine = mod.build_engine  # type: ignore[attr-defined]

    for name in sorted(names):
        info = CATALOG[name]
        engine = models_dir / info.engine_file
        onnx = models_dir / info.onnx_file
        if engine.exists():
            continue
        # fallback to baked ONNX if volume copy failed / model not yet copied
        if not onnx.exists() and (BAKED_DIR / info.onnx_file).exists():
            onnx = BAKED_DIR / info.onnx_file
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
