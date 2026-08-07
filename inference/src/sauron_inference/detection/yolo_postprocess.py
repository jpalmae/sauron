from __future__ import annotations

import cv2
import numpy as np

from ..types import Detection


def letterbox(
    image: np.ndarray, new_shape: tuple[int, int] = (640, 640)
) -> tuple[np.ndarray, float, tuple[float, float]]:
    """Resize with unchanged aspect ratio using padding. Returns (img, scale, (dw, dh))."""
    h, w = image.shape[:2]
    new_w, new_h = new_shape
    scale = min(new_w / w, new_h / h)
    resize_w, resize_h = round(w * scale), round(h * scale)
    dw, dh = (new_w - resize_w) / 2, (new_h - resize_h) / 2

    resized = cv2.resize(image, (resize_w, resize_h), interpolation=cv2.INTER_LINEAR)
    top, bottom = round(dh - 0.1), round(dh + 0.1)
    left, right = round(dw - 0.1), round(dw + 0.1)
    out = cv2.copyMakeBorder(
        resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114)
    )
    return out, scale, (dw, dh)


def xywh_to_xyxy(boxes: np.ndarray) -> np.ndarray:
    out = np.empty_like(boxes)
    out[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
    out[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
    out[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
    out[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
    return out


def scale_boxes(
    boxes: np.ndarray,
    scale: float,
    pad: tuple[float, float],
    orig_shape: tuple[int, int],
) -> np.ndarray:
    """Map letterboxed xyxy boxes back to the original image coordinates."""
    dw, dh = pad
    boxes[:, [0, 2]] -= dw
    boxes[:, [1, 3]] -= dh
    boxes /= scale
    h, w = orig_shape
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w - 1)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h - 1)
    return boxes


def postprocess_yolo(
    output: np.ndarray,
    orig_shape: tuple[int, int],
    scale: float,
    pad: tuple[float, float],
    conf_threshold: float,
    nms_threshold: float,
    classes: dict[int, str],
) -> list[Detection]:
    """YOLOv8 output [1, 4+nc, N] -> filtered Detections in original image space."""
    preds = output[0].T  # [N, 4+nc]
    boxes = xywh_to_xyxy(preds[:, :4].astype(np.float32))
    scores_per_class = preds[:, 4:]

    class_ids = np.argmax(scores_per_class, axis=1)
    scores = scores_per_class[np.arange(len(preds)), class_ids]

    keep = scores >= conf_threshold
    boxes, scores, class_ids = boxes[keep], scores[keep], class_ids[keep]
    if len(boxes) == 0:
        return []

    indices = cv2.dnn.NMSBoxes(
        bboxes=boxes.tolist(),
        scores=scores.tolist(),
        score_threshold=conf_threshold,
        nms_threshold=nms_threshold,
    )
    if len(indices) == 0:
        return []
    keep_idx = np.asarray(indices).flatten()

    boxes = scale_boxes(boxes[keep_idx], scale, pad, orig_shape)
    detections: list[Detection] = []
    for box, score, cls_id in zip(boxes, scores[keep_idx], class_ids[keep_idx]):
        cls = int(cls_id)
        if cls not in classes:
            continue
        detections.append(
            Detection(bbox=box.astype(np.float32), score=float(score), class_id=cls, class_name=classes[cls])
        )
    return detections


def postprocess_yolo_pose(
    output: np.ndarray,
    orig_shape: tuple[int, int],
    scale: float,
    pad: tuple[float, float],
    conf_threshold: float,
    nms_threshold: float,
) -> list[tuple[np.ndarray, float, np.ndarray]]:
    """YOLOv8-pose output [1, 56, N] -> [(bbox_xyxy, score, keypoints[17,3]), ...].

    Layout per anchor: [cx, cy, w, h, conf, kx0, ky0, kc0, ... x17].
    Coordinates are mapped back to the original image space.
    """
    preds = output[0].T  # [N, 56]
    boxes = xywh_to_xyxy(preds[:, :4].astype(np.float32))
    scores = preds[:, 4]
    kpts = preds[:, 5:].reshape(-1, 17, 3).astype(np.float32)

    keep = scores >= conf_threshold
    boxes, scores, kpts = boxes[keep], scores[keep], kpts[keep]
    if len(boxes) == 0:
        return []

    indices = cv2.dnn.NMSBoxes(
        bboxes=boxes.tolist(),
        scores=scores.tolist(),
        score_threshold=conf_threshold,
        nms_threshold=nms_threshold,
    )
    if len(indices) == 0:
        return []
    idx = np.asarray(indices).flatten()

    boxes = scale_boxes(boxes[idx], scale, pad, orig_shape)
    kpts = kpts[idx].copy()
    kpts[:, :, 0] = (kpts[:, :, 0] - pad[0]) / scale
    kpts[:, :, 1] = (kpts[:, :, 1] - pad[1]) / scale

    return [
        (boxes[i].astype(np.float32), float(scores[i]), kpts[i].astype(np.float32))
        for i in range(len(idx))
    ]
