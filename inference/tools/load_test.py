#!/usr/bin/env python3
"""Load test: N synthetic streams through detect+track+rules, measuring per-stream FPS.

Runs the full pipeline (mock detector) without cameras or GPU — validates that
the host CPU/threading model sustains the per-stream FPS target before the GPU
inference stage becomes the bottleneck.

Usage:
    python tools/load_test.py --streams 20 --duration 30 --fps 15
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

sys.path.insert(0, "src")

from sauron_inference.capture.synthetic import SyntheticSource
from sauron_inference.config import TrackerConfig
from sauron_inference.detection.mock import MockDetector
from sauron_inference.pipeline.stream import StreamPipeline
from sauron_inference.tracking.bytetrack import BYTETracker


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--streams", type=int, default=20)
    ap.add_argument("--duration", type=float, default=30.0, help="seconds")
    ap.add_argument("--fps", type=int, default=15, help="target fps per stream")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()

    pipelines = [
        StreamPipeline(
            source=SyntheticSource(
                f"load-{i:02d}", width=args.width, height=args.height, target_fps=args.fps
            ),
            detector=MockDetector(),
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
    print(f"\n{args.streams} streams x {args.fps} fps target — {elapsed:.0f}s window")
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
