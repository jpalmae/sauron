from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CLASS_ALIASES = {
    "automobile": "car",
    "bike": "bicycle",
    "pedestrian": "person",
    "persons": "person",
    "road-sign": "roadsign",
    "road_sign": "roadsign",
    "vehicle": "car",
}


@dataclass(frozen=True, slots=True)
class ObjectLabel:
    class_name: str
    bbox: tuple[float, float, float, float]
    confidence: float | None = None
    track_id: str | None = None


@dataclass(frozen=True, slots=True)
class FrameLabels:
    camera_id: str
    frame_id: str
    objects: tuple[ObjectLabel, ...]


@dataclass(frozen=True, slots=True)
class EventLabel:
    camera_id: str
    event_type: str
    timestamp: float
    rule_id: str = ""
    class_name: str = ""
    direction: str = ""

    @property
    def group(self) -> tuple[str, str, str, str, str]:
        return (
            self.camera_id,
            self.event_type,
            self.rule_id,
            self.class_name,
            self.direction,
        )


@dataclass(frozen=True, slots=True)
class PerformanceSample:
    camera_id: str
    frames: int
    elapsed_seconds: float
    target_fps: float

    @property
    def fps(self) -> float:
        return self.frames / self.elapsed_seconds if self.elapsed_seconds > 0 else 0.0


@dataclass(frozen=True, slots=True)
class AcceptanceThresholds:
    min_precision: float = 0.80
    min_recall: float = 0.80
    max_count_error_pct: float = 10.0
    min_fps_ratio: float = 0.90


@dataclass(slots=True)
class _Counter:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        denominator = self.precision + self.recall
        return 2 * self.precision * self.recall / denominator if denominator else 0.0

    def to_dict(self) -> dict[str, int | float]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


@dataclass(slots=True)
class EvaluationInputs:
    frames: list[FrameLabels] = field(default_factory=list)
    events: list[EventLabel] = field(default_factory=list)
    performance: list[PerformanceSample] = field(default_factory=list)


def _canonical_class(value: Any, aliases: dict[str, str]) -> str:
    name = str(value or "unknown").strip().lower()
    return aliases.get(name, name)


def _normalized_bbox(value: Any) -> tuple[float, float, float, float]:
    if not isinstance(value, list | tuple) or len(value) != 4:
        raise ValueError("bbox must contain [x1, y1, x2, y2]")
    x1, y1, x2, y2 = (float(item) for item in value)
    bbox = (x1, y1, x2, y2)
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise ValueError(f"bbox must be normalized to 0..1, got {bbox}")
    return bbox


def load_jsonl(path: Path, aliases: dict[str, str] | None = None) -> EvaluationInputs:
    aliases = {**DEFAULT_CLASS_ALIASES, **(aliases or {})}
    result = EvaluationInputs()
    with path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
                kind = item.get("kind", "frame")
                if kind == "frame":
                    objects = tuple(
                        ObjectLabel(
                            class_name=_canonical_class(
                                obj.get("class", obj.get("class_name")), aliases
                            ),
                            bbox=_normalized_bbox(obj["bbox"]),
                            confidence=(
                                float(obj["confidence"])
                                if obj.get("confidence") is not None
                                else None
                            ),
                            track_id=(
                                str(obj.get("track_id", obj.get("id")))
                                if obj.get("track_id", obj.get("id")) is not None
                                else None
                            ),
                        )
                        for obj in item.get("objects", [])
                        if not obj.get("ignore", False)
                    )
                    result.frames.append(
                        FrameLabels(str(item["camera_id"]), str(item["frame_id"]), objects)
                    )
                elif kind == "event":
                    result.events.append(
                        EventLabel(
                            camera_id=str(item["camera_id"]),
                            event_type=str(item["event_type"]),
                            timestamp=float(item["timestamp"]),
                            rule_id=str(item.get("rule_id", "")),
                            class_name=_canonical_class(item.get("class", ""), aliases)
                            if item.get("class")
                            else "",
                            direction=str(item.get("direction", "")),
                        )
                    )
                elif kind == "performance":
                    result.performance.append(
                        PerformanceSample(
                            camera_id=str(item["camera_id"]),
                            frames=int(item["frames"]),
                            elapsed_seconds=float(item["elapsed_seconds"]),
                            target_fps=float(item["target_fps"]),
                        )
                    )
                else:
                    raise ValueError(f"unsupported record kind {kind!r}")
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
    return result


def load_coco(
    path: Path,
    default_camera_id: str = "default",
    aliases: dict[str, str] | None = None,
) -> EvaluationInputs:
    aliases = {**DEFAULT_CLASS_ALIASES, **(aliases or {})}
    payload = json.loads(path.read_text(encoding="utf-8"))
    categories = {
        int(item["id"]): _canonical_class(item["name"], aliases)
        for item in payload.get("categories", [])
    }
    annotations: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for annotation in payload.get("annotations", []):
        if not annotation.get("iscrowd", 0) and not annotation.get("ignore", False):
            annotations[int(annotation["image_id"])].append(annotation)

    frames: list[FrameLabels] = []
    for image in payload.get("images", []):
        image_id = int(image["id"])
        width = float(image["width"])
        height = float(image["height"])
        if width <= 0 or height <= 0:
            raise ValueError(f"image {image_id}: width and height must be positive")
        objects: list[ObjectLabel] = []
        for annotation in annotations.get(image_id, []):
            x, y, w, h = (float(value) for value in annotation["bbox"])
            if w <= 0 or h <= 0:
                continue
            objects.append(
                ObjectLabel(
                    class_name=categories[int(annotation["category_id"])],
                    bbox=(x / width, y / height, (x + w) / width, (y + h) / height),
                    track_id=(
                        str(annotation["track_id"])
                        if annotation.get("track_id") is not None
                        else None
                    ),
                )
            )
        frames.append(
            FrameLabels(
                camera_id=str(image.get("camera_id", default_camera_id)),
                frame_id=str(image.get("frame_id", image["file_name"])),
                objects=tuple(objects),
            )
        )
    return EvaluationInputs(frames=frames)


def intersection_over_union(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> float:
    x1 = max(left[0], right[0])
    y1 = max(left[1], right[1])
    x2 = min(left[2], right[2])
    y2 = min(left[3], right[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def _match_objects(
    truth: tuple[ObjectLabel, ...],
    predictions: tuple[ObjectLabel, ...],
    iou_threshold: float,
) -> tuple[list[tuple[int, int]], set[int], set[int]]:
    candidates: list[tuple[float, int, int]] = []
    for truth_index, expected in enumerate(truth):
        for prediction_index, predicted in enumerate(predictions):
            if expected.class_name != predicted.class_name:
                continue
            iou = intersection_over_union(expected.bbox, predicted.bbox)
            if iou >= iou_threshold:
                candidates.append((iou, truth_index, prediction_index))
    matches: list[tuple[int, int]] = []
    used_truth: set[int] = set()
    used_predictions: set[int] = set()
    for _, truth_index, prediction_index in sorted(candidates, reverse=True):
        if truth_index in used_truth or prediction_index in used_predictions:
            continue
        used_truth.add(truth_index)
        used_predictions.add(prediction_index)
        matches.append((truth_index, prediction_index))
    return matches, set(range(len(truth))) - used_truth, set(range(len(predictions))) - used_predictions


def _detection_metrics(
    truth: list[FrameLabels],
    predictions: list[FrameLabels],
    iou_threshold: float,
    min_confidence: float,
) -> dict[str, Any]:
    truth_by_frame = {(frame.camera_id, frame.frame_id): frame for frame in truth}
    prediction_by_frame = {(frame.camera_id, frame.frame_id): frame for frame in predictions}
    counters: dict[tuple[str, str], _Counter] = defaultdict(_Counter)
    overall = _Counter()
    matched_ious: list[float] = []

    for key in sorted(set(truth_by_frame) | set(prediction_by_frame)):
        expected = truth_by_frame.get(key, FrameLabels(key[0], key[1], ()))
        raw_predicted = prediction_by_frame.get(key, FrameLabels(key[0], key[1], ()))
        predicted = FrameLabels(
            raw_predicted.camera_id,
            raw_predicted.frame_id,
            tuple(
                item
                for item in raw_predicted.objects
                if item.confidence is None or item.confidence >= min_confidence
            ),
        )
        matches, false_negatives, false_positives = _match_objects(
            expected.objects, predicted.objects, iou_threshold
        )
        for truth_index, prediction_index in matches:
            class_name = expected.objects[truth_index].class_name
            counters[(key[0], class_name)].tp += 1
            overall.tp += 1
            matched_ious.append(
                intersection_over_union(
                    expected.objects[truth_index].bbox,
                    predicted.objects[prediction_index].bbox,
                )
            )
        for truth_index in false_negatives:
            counters[(key[0], expected.objects[truth_index].class_name)].fn += 1
            overall.fn += 1
        for prediction_index in false_positives:
            counters[(key[0], predicted.objects[prediction_index].class_name)].fp += 1
            overall.fp += 1

    rows = [
        {"camera_id": camera_id, "class": class_name, **counter.to_dict()}
        for (camera_id, class_name), counter in sorted(counters.items())
    ]
    return {
        "frames_ground_truth": len(truth_by_frame),
        "frames_predicted": len(prediction_by_frame),
        "iou_threshold": iou_threshold,
        "min_confidence": min_confidence,
        "mean_matched_iou": round(sum(matched_ious) / len(matched_ious), 4)
        if matched_ious
        else 0.0,
        "overall": overall.to_dict(),
        "by_camera_class": rows,
    }


def _event_metrics(
    truth: list[EventLabel], predictions: list[EventLabel], tolerance_seconds: float
) -> dict[str, Any] | None:
    if not truth and not predictions:
        return None
    truth_groups: dict[tuple[str, str, str, str, str], list[EventLabel]] = defaultdict(list)
    prediction_groups: dict[tuple[str, str, str, str, str], list[EventLabel]] = defaultdict(list)
    for event in truth:
        truth_groups[event.group].append(event)
    for event in predictions:
        prediction_groups[event.group].append(event)

    overall = _Counter()
    rows: list[dict[str, Any]] = []
    for group in sorted(set(truth_groups) | set(prediction_groups)):
        expected = sorted(truth_groups[group], key=lambda item: item.timestamp)
        predicted = sorted(prediction_groups[group], key=lambda item: item.timestamp)
        available = set(range(len(predicted)))
        matched = 0
        for event in expected:
            candidates = [
                (abs(event.timestamp - predicted[index].timestamp), index)
                for index in available
                if abs(event.timestamp - predicted[index].timestamp) <= tolerance_seconds
            ]
            if not candidates:
                continue
            _, index = min(candidates)
            available.remove(index)
            matched += 1
        counter = _Counter(tp=matched, fp=len(predicted) - matched, fn=len(expected) - matched)
        overall.tp += counter.tp
        overall.fp += counter.fp
        overall.fn += counter.fn
        expected_count = len(expected)
        predicted_count = len(predicted)
        absolute_error = abs(predicted_count - expected_count)
        error_pct = (
            absolute_error / expected_count * 100
            if expected_count
            else (0.0 if predicted_count == 0 else math.inf)
        )
        rows.append(
            {
                "camera_id": group[0],
                "event_type": group[1],
                "rule_id": group[2],
                "class": group[3],
                "direction": group[4],
                "expected_count": expected_count,
                "predicted_count": predicted_count,
                "absolute_error": absolute_error,
                "error_pct": round(error_pct, 2),
                **counter.to_dict(),
            }
        )
    total_expected = len(truth)
    total_predicted = len(predictions)
    total_error = abs(total_predicted - total_expected)
    total_error_pct = (
        total_error / total_expected * 100
        if total_expected
        else (0.0 if total_predicted == 0 else math.inf)
    )
    return {
        "tolerance_seconds": tolerance_seconds,
        "expected_count": total_expected,
        "predicted_count": total_predicted,
        "absolute_error": total_error,
        "error_pct": round(total_error_pct, 2),
        "overall": overall.to_dict(),
        "by_group": rows,
    }


def _performance_metrics(samples: list[PerformanceSample]) -> dict[str, Any] | None:
    if not samples:
        return None
    rows = [
        {
            **asdict(sample),
            "fps": round(sample.fps, 3),
            "fps_ratio": round(sample.fps / sample.target_fps, 4)
            if sample.target_fps > 0
            else 0.0,
        }
        for sample in samples
    ]
    return {"by_camera": rows}


def evaluate(
    ground_truth: EvaluationInputs,
    predictions: EvaluationInputs,
    *,
    iou_threshold: float = 0.50,
    min_confidence: float = 0.0,
    event_tolerance_seconds: float = 1.0,
    thresholds: AcceptanceThresholds | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or AcceptanceThresholds()
    if not ground_truth.frames and not ground_truth.events:
        raise ValueError("ground truth contains no frames or events")
    detections = _detection_metrics(
        ground_truth.frames, predictions.frames, iou_threshold, min_confidence
    )
    events = _event_metrics(
        ground_truth.events, predictions.events, event_tolerance_seconds
    )
    performance = _performance_metrics(predictions.performance)
    detection_rows = detections["by_camera_class"]
    has_detection_evidence = bool(ground_truth.frames)
    checks = {
        "precision_by_camera_class": not has_detection_evidence
        or bool(detection_rows)
        and all(row["precision"] >= thresholds.min_precision for row in detection_rows),
        "recall_by_camera_class": not has_detection_evidence
        or bool(detection_rows)
        and all(row["recall"] >= thresholds.min_recall for row in detection_rows),
        "count_error": events is None
        or all(
            row["error_pct"] <= thresholds.max_count_error_pct
            for row in events["by_group"]
        ),
        "fps": performance is None
        or all(
            row["fps_ratio"] >= thresholds.min_fps_ratio
            for row in performance["by_camera"]
        ),
    }
    return {
        "schema_version": 1,
        "passed": all(checks.values()),
        "checks": checks,
        "thresholds": asdict(thresholds),
        "detections": detections,
        "events": events,
        "performance": performance,
    }


def render_markdown(report: dict[str, Any]) -> str:
    status = "PASS" if report["passed"] else "FAIL"
    lines = [
        "# Sauron evaluation report",
        "",
        f"**Result: {status}**",
        "",
        "## Detection metrics",
        "",
        "| Camera | Class | Precision | Recall | F1 | TP | FP | FN |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["detections"]["by_camera_class"]:
        lines.append(
            "| {camera_id} | {class} | {precision:.3f} | {recall:.3f} | "
            "{f1:.3f} | {tp} | {fp} | {fn} |".format(**row)
        )
    events = report.get("events")
    if events:
        lines.extend(
            [
                "",
                "## Counting/event metrics",
                "",
                "| Camera | Event | Rule | Class | Direction | Expected | Predicted | Error |",
                "| --- | --- | --- | --- | --- | ---: | ---: | ---: |",
            ]
        )
        for row in events["by_group"]:
            lines.append(
                "| {camera_id} | {event_type} | {rule_id} | {class} | {direction} | "
                "{expected_count} | {predicted_count} | {error_pct:.2f}% |".format(**row)
            )
    performance = report.get("performance")
    if performance:
        lines.extend(
            [
                "",
                "## Performance",
                "",
                "| Camera | FPS | Target | Ratio |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for row in performance["by_camera"]:
            lines.append(
                "| {camera_id} | {fps:.3f} | {target_fps:.3f} | {fps_ratio:.3f} |".format(
                    **row
                )
            )
    lines.extend(["", "## Acceptance checks", ""])
    for name, passed in report["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'}: {name}")
    return "\n".join(lines) + "\n"


def _load_input(path: Path, camera_id: str) -> EvaluationInputs:
    return load_coco(path, camera_id) if path.suffix.lower() == ".json" else load_jsonl(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Sauron detections and analytics")
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--camera-id", default="default", help="COCO default camera id")
    parser.add_argument("--output", required=True, type=Path, help="Markdown report path")
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--iou", type=float, default=0.50)
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument("--event-tolerance", type=float, default=1.0)
    parser.add_argument("--min-precision", type=float, default=0.80)
    parser.add_argument("--min-recall", type=float, default=0.80)
    parser.add_argument("--max-count-error-pct", type=float, default=10.0)
    parser.add_argument("--min-fps-ratio", type=float, default=0.90)
    args = parser.parse_args()
    report = evaluate(
        _load_input(args.ground_truth, args.camera_id),
        load_jsonl(args.predictions),
        iou_threshold=args.iou,
        min_confidence=args.min_confidence,
        event_tolerance_seconds=args.event_tolerance,
        thresholds=AcceptanceThresholds(
            min_precision=args.min_precision,
            min_recall=args.min_recall,
            max_count_error_pct=args.max_count_error_pct,
            min_fps_ratio=args.min_fps_ratio,
        ),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_markdown(report), encoding="utf-8")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(0 if report["passed"] else 2)


if __name__ == "__main__":
    main()
