from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

CATEGORIES = [
    {"id": 1, "name": "car"},
    {"id": 2, "name": "bicycle"},
    {"id": 3, "name": "person"},
    {"id": 4, "name": "roadsign"},
]


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-.") or "camera"


def _ensure_empty_directory(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"output directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def _health_frames(payload: dict[str, Any], stream_id: str) -> int:
    camera = payload.get("cameras", {}).get(stream_id, {})
    return int(camera.get("frames", 0))


def capture(
    *,
    camera_id: str,
    stream_id: str,
    output: Path,
    token: str,
    api_url: str = "http://127.0.0.1:8000",
    go2rtc_url: str = "http://127.0.0.1:1984",
    go2rtc_stream: str | None = None,
    health_url: str = "http://127.0.0.1:9100/healthz",
    samples: int = 30,
    interval_seconds: float = 1.0,
    target_fps: float = 10.0,
    max_capture_seconds: float | None = None,
) -> dict[str, Any]:
    if samples <= 0:
        raise ValueError("samples must be positive")
    if interval_seconds < 0:
        raise ValueError("interval_seconds cannot be negative")
    _ensure_empty_directory(output)
    workspace_context = tempfile.TemporaryDirectory(prefix="sauron-eval-")
    workspace = Path(workspace_context.name)
    images_dir = workspace / "images"
    images_dir.mkdir()
    headers = {"Authorization": f"Bearer {token}"}
    safe_stream = _safe_name(stream_id)
    snapshot_stream = go2rtc_stream or stream_id
    prediction_records: list[dict[str, Any]] = []
    coco_images: list[dict[str, Any]] = []
    seen_frames: set[str] = set()

    with httpx.Client(timeout=15, follow_redirects=True) as client:
        start_health = client.get(health_url).raise_for_status().json()
        started = time.monotonic()
        budget = max_capture_seconds or max(60.0, samples * (interval_seconds + 15.0))
        deadline = started + budget
        last_error = ""
        while len(coco_images) < samples and time.monotonic() < deadline:
            try:
                detections = client.get(
                    f"{api_url.rstrip('/')}/api/v1/cameras/{camera_id}/detections",
                    headers=headers,
                ).raise_for_status().json()
            except httpx.HTTPError as error:
                last_error = str(error)
                time.sleep(max(interval_seconds, 0.1))
                continue
            if detections.get("status") != "live" or detections.get("frame_seq") is None:
                time.sleep(max(interval_seconds, 0.1))
                continue
            frame_seq = str(detections["frame_seq"])
            if frame_seq in seen_frames:
                time.sleep(max(interval_seconds / 4, 0.05))
                continue
            try:
                snapshot = client.get(
                    f"{go2rtc_url.rstrip('/')}/api/frame.jpeg", params={"src": snapshot_stream}
                ).raise_for_status()
            except httpx.HTTPError as error:
                last_error = str(error)
                time.sleep(max(interval_seconds, 0.1))
                continue
            if not snapshot.content.startswith(b"\xff\xd8"):
                last_error = "go2rtc snapshot endpoint did not return a JPEG image"
                time.sleep(max(interval_seconds, 0.1))
                continue
            frame_id = f"{safe_stream}-{int(detections['frame_seq']):010d}.jpg"
            (images_dir / frame_id).write_bytes(snapshot.content)
            seen_frames.add(frame_seq)
            width = int(detections["width"])
            height = int(detections["height"])
            coco_images.append(
                {
                    "id": len(coco_images) + 1,
                    "file_name": frame_id,
                    "frame_id": frame_id,
                    "camera_id": stream_id,
                    "width": width,
                    "height": height,
                    "timestamp": detections.get("ts"),
                }
            )
            prediction_records.append(
                {
                    "kind": "frame",
                    "camera_id": stream_id,
                    "frame_id": frame_id,
                    "timestamp": detections.get("ts"),
                    "width": width,
                    "height": height,
                    "objects": [
                        {
                            "class": item["class"],
                            "bbox": item["box"],
                            "confidence": item.get("confidence"),
                            "track_id": item.get("id"),
                            "vehicle_type": item.get("vehicle_type"),
                        }
                        for item in detections.get("objects", [])
                    ],
                }
            )
            if len(coco_images) < samples:
                time.sleep(interval_seconds)
        elapsed = time.monotonic() - started
        end_health = client.get(health_url).raise_for_status().json()

    if len(coco_images) < samples:
        workspace_context.cleanup()
        detail = f": {last_error}" if last_error else ""
        raise RuntimeError(
            f"captured {len(coco_images)} of {samples} requested frames{detail}"
        )
    frames_delta = max(
        0,
        _health_frames(end_health, stream_id) - _health_frames(start_health, stream_id),
    )
    prediction_records.append(
        {
            "kind": "performance",
            "camera_id": stream_id,
            "frames": frames_delta,
            "elapsed_seconds": round(elapsed, 6),
            "target_fps": target_fps,
        }
    )
    predictions_path = workspace / "predictions.jsonl"
    predictions_path.write_text(
        "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in prediction_records),
        encoding="utf-8",
    )
    ground_truth = {
        "info": {
            "description": "Sauron benchmark ground truth — label before evaluation",
            "version": "1",
        },
        "images": coco_images,
        "annotations": [],
        "categories": CATEGORIES,
    }
    (workspace / "ground-truth.coco.json").write_text(
        json.dumps(ground_truth, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "camera_id": camera_id,
        "stream_id": stream_id,
        "go2rtc_stream": snapshot_stream,
        "samples": len(coco_images),
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "instructions": [
            "Import images/ and ground-truth.coco.json into CVAT or another COCO editor.",
            "Label every car, bicycle, person and roadsign; do not copy predictions as truth.",
            "Export COCO instances over ground-truth.coco.json and run sauron-evaluate.",
        ],
    }
    (workspace / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    for item in workspace.iterdir():
        shutil.move(str(item), output / item.name)
    workspace_context.cleanup()
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture a Sauron evaluation pack")
    parser.add_argument("--camera-id", required=True, help="Camera UUID in the API")
    parser.add_argument("--stream-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--go2rtc-url", default="http://127.0.0.1:1984")
    parser.add_argument("--go2rtc-stream", help="Snapshot source when it differs from stream-id")
    parser.add_argument("--health-url", default="http://127.0.0.1:9100/healthz")
    parser.add_argument("--token-env", default="SAURON_TOKEN")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--target-fps", type=float, default=10.0)
    parser.add_argument(
        "--max-seconds", type=float, help="Overall capture deadline; default scales with samples"
    )
    args = parser.parse_args()
    token = os.environ.get(args.token_env, "")
    if not token:
        parser.error(f"environment variable {args.token_env} is required")
    manifest = capture(
        camera_id=args.camera_id,
        stream_id=args.stream_id,
        output=args.output,
        token=token,
        api_url=args.api_url,
        go2rtc_url=args.go2rtc_url,
        go2rtc_stream=args.go2rtc_stream,
        health_url=args.health_url,
        samples=args.samples,
        interval_seconds=args.interval,
        target_fps=args.target_fps,
        max_capture_seconds=args.max_seconds,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
