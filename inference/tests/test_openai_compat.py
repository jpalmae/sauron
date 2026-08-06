import json

import httpx
import numpy as np

from sauron_inference.config import OpenAIDetectorConfig
from sauron_inference.detection.openai_compat import (
    OpenAICompatDetector,
    parse_detections,
)

CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
SHAPE = (720, 1280)  # h, w


def test_parse_normalized_coords():
    content = '[{"class": "car", "bbox": [0.1, 0.2, 0.3, 0.5], "confidence": 0.9}]'
    dets = parse_detections(content, SHAPE, CLASSES, 0.5)
    assert len(dets) == 1
    d = dets[0]
    assert d.class_name == "car"
    assert d.class_id == 2
    np.testing.assert_allclose(d.bbox, [128, 144, 384, 360], rtol=1e-4)


def test_parse_with_code_fences_and_prose():
    content = 'Sure! Here are the detections:\n```json\n[{"class": "truck", "bbox": [10, 20, 110, 220], "confidence": 0.8}]\n```'
    dets = parse_detections(content, SHAPE, CLASSES, 0.5)
    assert len(dets) == 1
    assert dets[0].class_name == "truck"
    # pixel coords pass through
    np.testing.assert_allclose(dets[0].bbox, [10, 20, 110, 220])


def test_filters_low_conf_unknown_class_and_garbage():
    assert parse_detections("no vehicles here", SHAPE, CLASSES, 0.5) == []
    assert parse_detections("[]", SHAPE, CLASSES, 0.5) == []
    content = json.dumps(
        [
            {"class": "car", "bbox": [0, 0, 0.1, 0.1], "confidence": 0.3},  # low conf
            {"class": "person", "bbox": [0, 0, 0.1, 0.1], "confidence": 0.9},  # not a vehicle
            {"class": "bus", "bbox": [0.5, 0.5, 0.4, 0.6]},  # inverted box, no conf
            {"garbage": True},
        ]
    )
    assert parse_detections(content, SHAPE, CLASSES, 0.5) == []


def _client_with_response(payload: dict, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content)
        assert body["messages"][0]["content"][1]["type"] == "image_url"
        assert body["messages"][0]["content"][1]["image_url"]["url"].startswith(
            "data:image/jpeg;base64,"
        )
        return httpx.Response(status, json=payload)

    return httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://fake/v1"
    )


def test_detector_end_to_end():
    payload = {
        "choices": [
            {
                "message": {
                    "content": '[{"class": "motorcycle", "bbox": [0.5, 0.5, 0.6, 0.6], "confidence": 0.88}]'
                }
            }
        ]
    }
    det = OpenAICompatDetector(
        OpenAIDetectorConfig(), CLASSES, 0.5, client=_client_with_response(payload)
    )
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    dets = det.detect(img)
    assert len(dets) == 1
    assert dets[0].class_name == "motorcycle"
    assert dets[0].score == 0.88


def test_detector_http_error_returns_empty():
    det = OpenAICompatDetector(
        OpenAIDetectorConfig(), CLASSES, 0.5, client=_client_with_response({}, status=500)
    )
    assert det.detect(np.zeros((100, 100, 3), dtype=np.uint8)) == []


def test_detector_malformed_api_response_returns_empty():
    det = OpenAICompatDetector(
        OpenAIDetectorConfig(), CLASSES, 0.5, client=_client_with_response({"choices": []})
    )
    assert det.detect(np.zeros((100, 100, 3), dtype=np.uint8)) == []
