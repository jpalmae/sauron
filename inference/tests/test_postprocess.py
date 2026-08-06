import numpy as np

from sauron_inference.detection.yolo_postprocess import (
    letterbox,
    postprocess_yolo,
    scale_boxes,
    xywh_to_xyxy,
)


def test_letterbox_preserves_aspect():
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    out, scale, (dw, dh) = letterbox(img, (640, 640))
    assert out.shape == (640, 640, 3)
    assert scale == 0.5
    assert dw == 0
    assert dh == 140


def test_xywh_to_xyxy():
    boxes = np.array([[100.0, 100.0, 50.0, 40.0]])
    out = xywh_to_xyxy(boxes)
    np.testing.assert_allclose(out, [[75.0, 80.0, 125.0, 120.0]])


def test_scale_boxes_roundtrip():
    boxes = np.array([[320.0, 320.0, 420.0, 400.0]])
    out = scale_boxes(boxes.copy(), scale=0.5, pad=(0.0, 80.0), orig_shape=(720, 1280))
    np.testing.assert_allclose(out, [[640.0, 480.0, 840.0, 640.0]], rtol=1e-5)


def _fake_yolo_output(dets):
    """Build a [1, 4+80, N] YOLOv8 output from (cx, cy, w, h, cls, score) tuples."""
    n = len(dets)
    out = np.zeros((1, 84, n), dtype=np.float32)
    for i, (cx, cy, w, h, cls, score) in enumerate(dets):
        out[0, 0, i] = cx
        out[0, 1, i] = cy
        out[0, 2, i] = w
        out[0, 3, i] = h
        out[0, 4 + cls, i] = score
    return out


def test_postprocess_filters_and_maps():
    # one car with high conf inside the letterbox area, one low conf, one non-vehicle
    out = _fake_yolo_output(
        [
            (320.0, 400.0, 100.0, 60.0, 2, 0.9),   # car, keep
            (100.0, 400.0, 80.0, 50.0, 2, 0.3),    # low conf, drop
            (500.0, 400.0, 60.0, 60.0, 0, 0.95),   # person, filtered by class map
        ]
    )
    classes = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
    dets = postprocess_yolo(
        out,
        orig_shape=(720, 1280),
        scale=0.5,
        pad=(0.0, 80.0),
        conf_threshold=0.5,
        nms_threshold=0.45,
        classes=classes,
    )
    assert len(dets) == 1
    assert dets[0].class_name == "car"
    assert dets[0].score >= 0.5
    x1, y1, x2, y2 = dets[0].bbox
    assert x2 > x1 and y2 > y1
    assert 0 <= y1 and y2 <= 719


def test_postprocess_empty_when_all_below_conf():
    out = _fake_yolo_output([(320.0, 320.0, 50.0, 50.0, 2, 0.1)])
    dets = postprocess_yolo(
        out, (720, 1280), 0.5, (0.0, 80.0), 0.5, 0.45, {2: "car"}
    )
    assert dets == []
