import json

from sauron_deepstream import evaluation_capture


class _Response:
    def __init__(self, *, payload=None, content=b""):
        self._payload = payload
        self.content = content

    def raise_for_status(self):
        return self

    def json(self):
        return self._payload


class _Client:
    def __init__(self, *args, **kwargs):
        self.health_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def get(self, url, **kwargs):
        if url.endswith("/healthz"):
            self.health_calls += 1
            frames = 100 if self.health_calls == 1 else 110
            return _Response(payload={"cameras": {"cam": {"frames": frames}}})
        if url.endswith("/detections"):
            return _Response(
                payload={
                    "status": "live",
                    "frame_seq": 42,
                    "ts": 1000.0,
                    "width": 1280,
                    "height": 720,
                    "objects": [
                        {
                            "id": 7,
                            "class": "car",
                            "confidence": 0.91,
                            "box": [0.1, 0.2, 0.3, 0.4],
                        }
                    ],
                }
            )
        if url.endswith("/api/frame.jpeg"):
            return _Response(content=b"\xff\xd8fake-jpeg")
        raise AssertionError(url)


def test_capture_writes_coco_skeleton_predictions_and_performance(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation_capture.httpx, "Client", _Client)
    output = tmp_path / "pack"

    manifest = evaluation_capture.capture(
        camera_id="uuid",
        stream_id="cam",
        output=output,
        token="secret",
        samples=1,
        interval_seconds=0,
        target_fps=10,
    )

    assert manifest["samples"] == 1
    coco = json.loads((output / "ground-truth.coco.json").read_text())
    assert coco["annotations"] == []
    assert coco["images"][0]["camera_id"] == "cam"
    records = [json.loads(line) for line in (output / "predictions.jsonl").read_text().splitlines()]
    assert records[0]["objects"][0]["confidence"] == 0.91
    assert records[1]["kind"] == "performance"
    assert records[1]["frames"] == 10


def test_capture_refuses_non_empty_output(tmp_path):
    output = tmp_path / "pack"
    output.mkdir()
    (output / "keep.txt").write_text("important")

    try:
        evaluation_capture.capture(
            camera_id="uuid", stream_id="cam", output=output, token="secret", samples=1
        )
    except ValueError as error:
        assert "not empty" in str(error)
    else:
        raise AssertionError("expected capture to preserve an existing directory")
