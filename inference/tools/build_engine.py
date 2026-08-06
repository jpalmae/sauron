#!/usr/bin/env python3
"""Export YOLOv8 -> ONNX -> TensorRT .engine optimized for NVIDIA L4 (Ada Lovelace).

Usage (on the target GPU host):
    python tools/build_engine.py --weights yolov8n.pt --out models/yolov8n_fp16.engine --fp16
    python tools/build_engine.py --weights yolov8n.pt --out models/yolov8n_int8.engine --int8 --calib-data /data/calib
"""

from __future__ import annotations

import argparse
from pathlib import Path


def export_onnx(weights: str, onnx_path: Path, imgsz: int) -> Path:
    from ultralytics import YOLO

    model = YOLO(weights)
    model.export(format="onnx", imgsz=imgsz, simplify=True, opset=12, dynamic=False)
    default = Path(weights).with_suffix(".onnx")
    default.rename(onnx_path)
    return onnx_path


def build_engine(
    onnx_path: Path, out_path: Path, fp16: bool, int8: bool, workspace_gb: int
) -> None:
    import tensorrt as trt

    logger = trt.Logger(trt.Logger.INFO)
    builder = trt.Builder(logger)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, logger)
    if not parser.parse_from_file(str(onnx_path)):
        for i in range(parser.num_errors):
            logger.log(trt.Logger.ERROR, parser.get_error(i))
        raise SystemExit("ONNX parse failed")

    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, workspace_gb << 30)
    if fp16 and builder.platform_has_fast_fp16:
        config.set_flag(trt.BuilderFlag.FP16)
    if int8 and builder.platform_has_fast_int8:
        config.set_flag(trt.BuilderFlag.INT8)
        # TODO: plug an IInt8EntropyCalibrator2 with calibration images
        # (e.g. 500 frames sampled from production cameras)

    serialized = builder.build_serialized_network(network, config)
    if serialized is None:
        raise SystemExit("engine build failed")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(serialized))
    print(f"engine written to {out_path} ({out_path.stat().st_size / 1e6:.1f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True, help="YOLOv8 .pt weights")
    ap.add_argument("--out", required=True, help="output .engine path")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--fp16", action="store_true", default=True)
    ap.add_argument("--int8", action="store_true")
    ap.add_argument("--workspace-gb", type=int, default=4)
    ap.add_argument("--calib-data", default=None, help="dir with calibration frames (INT8)")
    args = ap.parse_args()

    onnx_path = Path(args.out).with_suffix(".onnx")
    export_onnx(args.weights, onnx_path, args.imgsz)
    build_engine(onnx_path, Path(args.out), args.fp16, args.int8, args.workspace_gb)


if __name__ == "__main__":
    main()
