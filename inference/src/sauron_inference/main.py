from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from .config import load_config
from .logging_setup import setup_logging
from .metrics import start_metrics_server
from .pipeline.manager import PipelineManager

log = logging.getLogger("sauron")


def _setup_logging(verbose: bool) -> None:
    setup_logging(verbose=verbose, json_format=os.environ.get("SAURON_LOG_FORMAT") == "json")


def _build_camera_source(cfg):
    """GUI-driven cameras: if SAURON_API_URL is set, streams come from the API."""
    api_url = os.environ.get("SAURON_API_URL", "").strip()
    if not api_url:
        return None
    from .camera_sync import APICameraSource

    ingest_token = os.environ.get("SAURON_INGEST_TOKEN", "").strip() or None
    fps = int(os.environ.get("SAURON_API_CAMERAS_FPS", "5"))
    interval = float(os.environ.get("SAURON_API_CAMERAS_POLL_S", "20"))
    log.info(
        "API camera source enabled: %s (poll every %ss, target_fps=%d)",
        api_url,
        interval,
        fps,
    )
    return APICameraSource(
        base_url=api_url,
        ingest_token=ingest_token,
        defaults=cfg.defaults,
        target_fps=fps,
        poll_interval=interval,
    )


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    log.info("loaded config: %d streams, devices=%s", len(cfg.streams), cfg.devices)
    camera_source = _build_camera_source(cfg)
    manager = PipelineManager(cfg, camera_source=camera_source)
    metrics_port = int(os.environ.get("SAURON_METRICS_PORT", "9100"))
    server = start_metrics_server(manager.metrics, port=metrics_port)
    log.info("metrics on :%d (/metrics, /healthz)", metrics_port)
    try:
        manager.run_forever()
    finally:
        server.shutdown()
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    from .capture.synthetic import SyntheticSource
    from .detection.mock import MockDetector
    from .pipeline.stream import StreamPipeline
    from .tracking.bytetrack import BYTETracker

    frames_target = args.frames
    done = {"count": 0, "start": 0.0}

    def on_tracks(camera_id, frame, tracks):
        if done["start"] == 0.0:
            done["start"] = time.monotonic()
        done["count"] += 1

    source = SyntheticSource(
        camera_id="bench",
        width=args.width,
        height=args.height,
        target_fps=args.fps,
        max_frames=frames_target + 30,
    )
    pipeline = StreamPipeline(
        source=source,
        detector=MockDetector(),
        tracker=BYTETracker(frame_rate=args.fps),
        on_tracks=on_tracks,
    )
    pipeline.start()
    t0 = time.monotonic()
    while done["count"] < frames_target and time.monotonic() - t0 < args.timeout:
        time.sleep(0.2)
    elapsed = time.monotonic() - done["start"] if done["start"] else 0.0
    pipeline.stop()

    fps = done["count"] / elapsed if elapsed > 0 else 0.0
    print(f"processed={done['count']} captured={pipeline.frames_captured} "
          f"dropped={pipeline.frames_dropped} elapsed={elapsed:.1f}s fps={fps:.1f}")
    return 0


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sauron-inference")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run all configured streams")
    p_run.add_argument("-c", "--config", default="configs/pipeline.yaml")
    p_run.set_defaults(func=cmd_run)

    p_bench = sub.add_parser("benchmark", help="throughput benchmark with synthetic source")
    p_bench.add_argument("--frames", type=int, default=300)
    p_bench.add_argument("--fps", type=int, default=60)
    p_bench.add_argument("--width", type=int, default=1280)
    p_bench.add_argument("--height", type=int, default=720)
    p_bench.add_argument("--timeout", type=float, default=60.0)
    p_bench.set_defaults(func=cmd_benchmark)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(cli())
