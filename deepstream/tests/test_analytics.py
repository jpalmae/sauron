from types import SimpleNamespace

import pytest

from sauron_deepstream.analytics import Detection, TrackAssembler, _classifier_label


def _object(object_id=42, left=10, top=20, width=30, height=40):
    return Detection(
        object_id=object_id,
        class_id=2,
        confidence=0.8,
        tracker_confidence=0.9,
        bbox=(left, top, left + width, top + height),
        vehicle_type=None,
    )


def test_track_assembler_builds_history_and_time_normalized_velocity():
    labels = [str(i) for i in range(80)]
    labels[2] = "car"
    assembler = TrackAssembler(labels, fps=10)

    first = assembler.assemble("cam", 1, 100.0, [_object()])[0]
    second = assembler.assemble("cam", 2, 100.1, [_object(left=20)])[0]

    assert first.class_name == "car"
    assert first.bbox == (10.0, 20.0, 40.0, 60.0)
    assert second.track_history == [(25.0, 40.0), (35.0, 40.0)]
    assert second.velocity[0] == pytest.approx(10.0)


def test_untracked_objects_are_ignored():
    assembler = TrackAssembler(["person"], fps=10)
    assert assembler.assemble("cam", 1, 1.0, [_object(object_id=0xFFFFFFFFFFFFFFFF)]) == []


def test_reads_vehicle_type_from_secondary_classifier():
    classifier = SimpleNamespace(
        unique_component_id=2,
        n_labels=1,
        get_n_label=lambda _index: "truck",
    )
    obj = SimpleNamespace(classifier_items=[classifier])
    assert _classifier_label(obj, 2) == "truck"
    assert _classifier_label(obj, 3) is None
