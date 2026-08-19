import json

import pytest

from sauron_deepstream.evaluation import (
    AcceptanceThresholds,
    EvaluationInputs,
    EventLabel,
    FrameLabels,
    ObjectLabel,
    PerformanceSample,
    evaluate,
    intersection_over_union,
    load_coco,
    load_jsonl,
    render_markdown,
)


def _object(class_name: str, bbox=(0.1, 0.1, 0.4, 0.4)) -> ObjectLabel:
    return ObjectLabel(class_name, bbox)


def test_iou_and_class_aware_detection_metrics():
    truth = EvaluationInputs(
        frames=[
            FrameLabels("cam", "one.jpg", (_object("car"), _object("person", (0.6, 0.1, 0.8, 0.5))))
        ]
    )
    predictions = EvaluationInputs(
        frames=[
            FrameLabels(
                "cam",
                "one.jpg",
                (_object("car"), _object("bicycle", (0.6, 0.1, 0.8, 0.5))),
            )
        ]
    )

    assert intersection_over_union((0, 0, 1, 1), (0.5, 0.5, 1, 1)) == pytest.approx(0.25)
    report = evaluate(truth, predictions)

    assert report["detections"]["overall"] == {
        "tp": 1,
        "fp": 1,
        "fn": 1,
        "precision": 0.5,
        "recall": 0.5,
        "f1": 0.5,
    }
    assert report["passed"] is False


def test_event_count_and_fps_acceptance():
    truth = EvaluationInputs(
        events=[
            EventLabel("cam", "LINE_CROSSING", 10.0, "L1", "car", "forward"),
            EventLabel("cam", "LINE_CROSSING", 20.0, "L1", "car", "forward"),
        ]
    )
    predictions = EvaluationInputs(
        events=[
            EventLabel("cam", "LINE_CROSSING", 10.4, "L1", "car", "forward"),
            EventLabel("cam", "LINE_CROSSING", 30.0, "L1", "car", "forward"),
        ],
        performance=[PerformanceSample("cam", frames=95, elapsed_seconds=10, target_fps=10)],
    )

    report = evaluate(
        truth,
        predictions,
        thresholds=AcceptanceThresholds(min_precision=0, min_recall=0),
    )

    assert report["events"]["overall"]["tp"] == 1
    assert report["events"]["overall"]["fp"] == 1
    assert report["events"]["overall"]["fn"] == 1
    assert report["events"]["error_pct"] == 0
    assert report["performance"]["by_camera"][0]["fps_ratio"] == 0.95
    assert report["passed"] is True


def test_missing_prediction_frame_counts_false_negatives():
    truth = EvaluationInputs(frames=[FrameLabels("cam", "one", (_object("car"),))])
    report = evaluate(truth, EvaluationInputs())
    assert report["detections"]["overall"]["fn"] == 1


def test_acceptance_is_per_camera_class_and_filters_confidence():
    truth = EvaluationInputs(
        frames=[
            FrameLabels("cam", "one", (_object("car"), _object("person", (0.6, 0.1, 0.8, 0.5))))
        ]
    )
    predictions = EvaluationInputs(
        frames=[
            FrameLabels(
                "cam",
                "one",
                (
                    ObjectLabel("car", (0.1, 0.1, 0.4, 0.4), confidence=0.9),
                    ObjectLabel("bicycle", (0.5, 0.5, 0.7, 0.7), confidence=0.1),
                ),
            )
        ]
    )
    report = evaluate(truth, predictions, min_confidence=0.3)
    rows = {row["class"]: row for row in report["detections"]["by_camera_class"]}
    assert "bicycle" not in rows
    assert rows["car"]["recall"] == 1
    assert rows["person"]["recall"] == 0
    assert report["checks"]["recall_by_camera_class"] is False


def test_loads_coco_and_jsonl_with_class_aliases(tmp_path):
    coco_path = tmp_path / "truth.json"
    coco_path.write_text(
        json.dumps(
            {
                "images": [
                    {
                        "id": 1,
                        "file_name": "one.jpg",
                        "camera_id": "cam",
                        "width": 100,
                        "height": 50,
                    }
                ],
                "categories": [{"id": 7, "name": "automobile"}],
                "annotations": [{"id": 2, "image_id": 1, "category_id": 7, "bbox": [10, 5, 20, 10]}],
            }
        ),
        encoding="utf-8",
    )
    jsonl_path = tmp_path / "predictions.jsonl"
    jsonl_path.write_text(
        json.dumps(
            {
                "kind": "frame",
                "camera_id": "cam",
                "frame_id": "one.jpg",
                "objects": [{"class": "vehicle", "bbox": [0.1, 0.1, 0.3, 0.3]}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    truth = load_coco(coco_path)
    predictions = load_jsonl(jsonl_path)
    report = evaluate(truth, predictions)

    assert truth.frames[0].objects[0].class_name == "car"
    assert report["passed"] is True
    assert "| cam | car | 1.000 | 1.000 |" in render_markdown(report)


def test_jsonl_rejects_non_normalized_bbox(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text(
        json.dumps(
            {
                "camera_id": "cam",
                "frame_id": "one",
                "objects": [{"class": "car", "bbox": [10, 10, 20, 20]}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="normalized"):
        load_jsonl(path)
