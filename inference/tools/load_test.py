#!/usr/bin/env python3
"""Load test N synthetic streams through detector + tracker.

The backend is explicit so a mock-only run cannot be confused with a production
capacity test. Use ``tensorrt`` on the target GPU for sizing.

Usage:
    python tools/load_test.py --backend tensorrt --model yolov8s --streams 20 --duration 30
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

sys.path.insert(0, "src")

from sauron_inference.capture.synthetic import SyntheticSource
from sauron_inference.config import TrackerConfig
from sauron_inference.detection.base import Detector
from sauron_inference.detection.mock import MockDetector
from sauron_inference.detection.onnx_dnn import OnnxDnnDetector
from sauron_inference.detection.tensorrt_yolo import TensorRTYolo
from sauron_inference.models import engine_path, model_imgsz, onnx_path
from sauron_inference.pipeline.stream import StreamPipeline
from sauron_inference.tracking.bytetrack import BYTETracker


def build_detector(backend: str, model: str) -> Detector:
    classes = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
    size = model_imgsz(model)
    if backend == "mock":
        return MockDetector(classes=classes)
    if backend == "onnx":
        return OnnxDnnDetector(onnx_path(model), input_size=(size, size), classes=classes)
    return TensorRTYolo(engine_path(model), input_size=(size, size), classes=classes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--streams", type=int, default=20)
    ap.add_argument("--duration", type=float, default=30.0, help="seconds")
    ap.add_argument("--fps", type=int, default=15, help="target fps per stream")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--backend", choices=["mock", "onnx", "tensorrt"], required=True)
    ap.add_argument("--model", default="yolov8s")
    args = ap.parse_args()

    pipelines = [
        StreamPipeline(
            source=SyntheticSource(
                f"load-{i:02d}", width=args.width, height=args.height, target_fps=args.fps
            ),
            detector=build_detector(args.backend, args.model),
            tracker=BYTETracker(TrackerConfig(), frame_rate=args.fps),
        )
        for i in range(args.streams)
    ]
    for p in pipelines:
        p.start()

    time.sleep(5)  # warmup
    start = {id(p): p.frames_processed for p in pipelines}
    t0 = time.monotonic()
    time.sleep(args.duration)
    elapsed = time.monotonic() - t0

    rows = []
    for p in pipelines:
        processed = p.frames_processed - start[id(p)]
        rows.append((p.source.camera_id, processed / elapsed, p.frames_dropped))
    for p in pipelines:
        p.stop()

    fps_values = [r[1] for r in rows]
    total_dropped = sum(r[2] for r in rows)
    print(
        f"\nbackend={args.backend} model={args.model} | "
        f"{args.streams} streams x {args.fps} fps target — {elapsed:.0f}s window"
    )
    print(f"  mean fps/stream : {statistics.mean(fps_values):.1f}")
    print(f"  min  fps/stream : {min(fps_values):.1f}")
    print(f"  p50  fps/stream : {statistics.median(fps_values):.1f}")
    print(f"  aggregate fps   : {sum(fps_values):.1f}")
    print(f"  dropped frames  : {total_dropped}")
    ok = min(fps_values) >= args.fps * 0.9
    print(f"  result          : {'PASS' if ok else 'FAIL'} (target >= {args.fps * 0.9:.1f} min)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
