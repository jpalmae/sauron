import httpx
import pytest

from sauron_alpr.config import Settings, StreamSpec, parse_streams
from sauron_alpr.runtime import ALPRRuntime, CameraState, normalize_plate, ocr_confidence


def make_settings(**overrides) -> Settings:
    defaults: dict = {
        "streams": parse_streams("cam-1"),
        "go2rtc_url": "http://go2rtc:1984",
        "rtsp_base": "rtsp://go2rtc:8554",
        "target_fps": 4.0,
        "stale_after_s": 30.0,
        "detector_model": "yolo-v9-s-608-license-plate-end2end",
        "detector_confidence": 0.25,
        "ocr_model": "cct-s-v2-global-model",
        "ocr_confidence": 0.65,
        "device": "cpu",
        "event_cooldown_s": 30.0,
        "api_url": "http://api:8000/api/v1",
        "ingest_token": "",
        "access_user": "",
        "access_password": "",
        "vehicle_api_url": "https://api.boostr.cl/vehicle/{plate}.json",
        "vehicle_api_key": "test-key",
        "vehicle_provider": "",
        "vehicle_cameras": "",
        "vehicle_include_owner": False,
        "matricula_username": "user",
        "matricula_key": "key",
        "matricula_endpoint": "https://www.regcheck.org.uk/api/reg.asmx",
        "matricula_operation": "CheckChile",
        "region": "",
        "reconcile_seconds": 15.0,
        "bestshot_wait_s": 4.0,
        "bestshot_conf": 0.95,
    }
    defaults.update(overrides)
    return Settings(**defaults)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self._payload


class FakeVehicleClient:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.calls: list[str] = []

    def get(self, url):
        self.calls.append(url)
        return FakeResponse(self.payload, self.status)


def test_parse_streams_supports_go2rtc_aliases():
    streams = parse_streams("cam-10, cam-166=cam-166-hd")

    assert [(stream.camera_id, stream.source) for stream in streams] == [
        ("cam-10", "cam-10"),
        ("cam-166", "cam-166-hd"),
    ]


def test_parse_streams_rejects_duplicate_camera_ids():
    with pytest.raises(ValueError, match="duplicate"):
        parse_streams("cam-10,cam-10=other")


def test_plate_normalization_and_confidence():
    assert normalize_plate("ab-cd 12") == "ABCD12"
    assert ocr_confidence([0.8, 0.6]) == pytest.approx(0.7)
    assert ocr_confidence([]) == 0.0


def test_camera_staleness_uses_configured_threshold():
    state = CameraState(StreamSpec(camera_id="cam-1", source="cam-1"))
    state.status = "live"
    state.last_frame_at = 100

    assert state.describe(129, stale_after_s=30)["status"] == "live"
    assert state.describe(131, stale_after_s=30)["status"] == "stale"


def test_vehicle_lookup_maps_boostr_payload_and_caches():
    runtime = ALPRRuntime(
        make_settings(
            vehicle_api_url="https://api.boostr.cl/vehicle/{plate}.json?key=x",
        )
    )
    client = FakeVehicleClient(
        {
            "status": "success",
            "data": {
                "plate": "XF2408",
                "dv": "3",
                "make": "PEUGEOT",
                "model": "407",
                "year": 2011,
                "type": "AUTOMOVIL",
                "engine": "XYZ123",
                "owner": {"fullname": "SECRETO", "documentNumber": "1-9"},
            },
        }
    )
    runtime._vehicle_client = client

    vehicle = runtime._vehicle_data("XF2408")
    assert vehicle == {
        "plate": "XF2408",
        "dv": "3",
        "make": "PEUGEOT",
        "model": "407",
        "year": 2011,
        "type": "AUTOMOVIL",
        "engine": "XYZ123",
    }
    assert "key=x" in client.calls[0]

    runtime._vehicle_data("XF2408")
    assert len(client.calls) == 1


def test_vehicle_lookup_error_is_negative_cached():
    runtime = ALPRRuntime(make_settings())
    client = FakeVehicleClient({"status": "error", "code": "V-02", "message": "no"}, status=200)
    runtime._vehicle_client = client

    assert runtime._vehicle_data("ZZZZ99") is None
    runtime._vehicle_data("ZZZZ99")
    assert len(client.calls) == 1


def test_reconcile_keeps_only_matriculas_cameras():
    from unittest.mock import Mock

    runtime = ALPRRuntime(make_settings())
    runtime._start_capture = Mock()
    runtime._stop_capture = Mock()
    runtime.states["cam-x"] = CameraState(StreamSpec(camera_id="cam-x", source="cam-x"))
    runtime.states["cam-keep"] = CameraState(StreamSpec(camera_id="cam-keep", source="cam-keep"))

    runtime._reconcile_cameras(
        [
            {
                "stream_id": "cam-keep",
                "analytics_profile": "matriculas",
                "rtsp_url": "rtsp://go2rtc:8554/cam-keep",
            },
            {
                "stream_id": "cam-other",
                "analytics_profile": "traffic",
                "rtsp_url": "rtsp://go2rtc:8554/cam-other",
            },
            {
                "stream_id": "cam-new",
                "analytics_profile": "matriculas",
                "rtsp_url": "rtsp://go2rtc:8554/cam-new-hd",
            },
        ]
    )

    runtime._stop_capture.assert_any_call("cam-x")
    runtime._start_capture.assert_called_once()
    added = runtime._start_capture.call_args.args[0]
    assert added.camera_id == "cam-new"
    assert added.source == "cam-new-hd"


def test_vehicle_lookup_disabled_without_api_key():
    runtime = ALPRRuntime(make_settings(vehicle_api_key=""))
    assert runtime._vehicle_data("XF2408") is None


def test_spec_from_payload_maps_go2rtc_urls():
    from sauron_alpr.runtime import ALPRRuntime as _  # noqa: F401  (import sanity)

    spec = ALPRRuntime._spec_from_payload(
        {"stream_id": "cam-43", "rtsp_url": "rtsp://go2rtc:8554/cam-43-hd"}
    )
    assert spec == StreamSpec(camera_id="cam-43", source="cam-43-hd")

    direct = ALPRRuntime._spec_from_payload(
        {"stream_id": "otra", "rtsp_url": "rtsp://10.0.0.5:554/live"}
    )
    assert direct == StreamSpec(camera_id="otra", source="rtsp://10.0.0.5:554/live")

    assert ALPRRuntime._spec_from_payload({"stream_id": "x", "rtsp_url": ""}) == StreamSpec(
        camera_id="x", source="x"
    )
    assert ALPRRuntime._spec_from_payload({"stream_id": ""}) is None


SOAP_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <CheckResponse xmlns="http://regcheck.org.uk">
      <CheckResult>
        <vehicleJson>{"Description":"BMW 116I M 1.6","RegistrationYear":"2012","CarMake":{"CurrentTextValue":"BMW"},"CarModel":{"CurrentTextValue":"116I M 1.6"},"VIN":"WBAUE1105CPZ56669","EngineCode":"A393I950","Fuel":"GASOLINA","Colour":"BLANCO","VehicleType":"AUTOMOVIL","Owner":{"Name":"ALARCON CONEJEROS HERNAN ESTEBAN","NationalId":"16287080-7"}}</vehicleJson>
      </CheckResult>
    </CheckResponse>
  </soap:Body>
</soap:Envelope>"""


def test_parse_soap_vehicle_maps_regcheck_fields():
    vehicle = ALPRRuntime._parse_soap_vehicle(SOAP_FIXTURE, "XF2408", include_owner=True)
    assert vehicle is not None
    assert vehicle["make"] == "BMW"
    assert vehicle["model"] == "116I M 1.6"
    assert vehicle["year"] == "2012"
    assert vehicle["color"] == "BLANCO"
    assert vehicle["fuel"] == "GASOLINA"
    assert vehicle["vin"] == "WBAUE1105CPZ56669"
    assert vehicle["provider"] == "matriculaapi"
    assert vehicle["owner"]["fullname"] == "ALARCON CONEJEROS HERNAN ESTEBAN"
    assert vehicle["owner"]["documentNumber"] == "16287080-7"


def test_parse_soap_vehicle_without_owner_flag():
    vehicle = ALPRRuntime._parse_soap_vehicle(SOAP_FIXTURE, "XF2408", include_owner=False)
    assert vehicle is not None
    assert "owner" not in vehicle


def test_best_shot_picks_highest_ocr_and_flushes_on_silence():
    from sauron_alpr.runtime import BestShotTracker

    emitted = []
    tracker = BestShotTracker(
        wait_s=4, emit_conf=0.99, emit=lambda cid, ts, det, jp: emitted.append((ts, det, jp))
    )

    def det(plate, ocr):
        return {
            "plate": plate,
            "ocr_confidence": ocr,
            "detector_confidence": 0.5,
            "box": [0, 0, 100, 40],
            "region": None,
        }

    tracker.update("cam", [det("5SMP26", 0.84)], b"j1", ts=100.0)
    tracker.update("cam", [det("SSMP26", 0.93)], b"j2", ts=100.5)
    tracker.update("cam", [det("SSMP26", 0.97)], b"j3", ts=101.0)
    assert emitted == []
    tracker.update("cam", [], b"j4", ts=106.0)
    assert len(emitted) == 1
    best, jp = emitted[0][1], emitted[0][2]
    assert best["plate"] == "SSMP26"
    assert best["ocr_confidence"] == 0.97
    assert jp == b"j3"


def test_best_shot_early_emit_on_high_conf():
    from sauron_alpr.runtime import BestShotTracker

    emitted = []
    tracker = BestShotTracker(
        wait_s=4, emit_conf=0.95, emit=lambda cid, ts, det, jp: emitted.append(det)
    )

    def det(plate, ocr):
        return {
            "plate": plate,
            "ocr_confidence": ocr,
            "detector_confidence": 0.6,
            "box": [0, 0, 120, 45],
            "region": None,
        }

    tracker.update("cam", [det("HWF533", 0.88)], b"a", ts=10.0)
    assert emitted == []
    tracker.update("cam", [det("HWF533", 0.98)], b"b", ts=10.5)
    assert len(emitted) == 1
    assert emitted[0]["ocr_confidence"] == 0.98


def test_best_shot_separates_different_vehicles():
    from sauron_alpr.runtime import BestShotTracker

    emitted = []
    tracker = BestShotTracker(
        wait_s=4, emit_conf=0.99, emit=lambda cid, ts, det, jp: emitted.append(det)
    )

    def det(plate, ocr, x=0):
        return {
            "plate": plate,
            "ocr_confidence": ocr,
            "detector_confidence": 0.5,
            "box": [x, 0, x + 100, 40],
            "region": None,
        }

    tracker.update("cam", [det("AAAA11", 0.8)], b"a", ts=10.0)
    tracker.update("cam", [det("ZZZZ99", 0.8, x=300)], b"b", ts=11.0)
    assert len(emitted) == 1
    assert emitted[0]["plate"] == "AAAA11"


def test_spec_from_payload_reads_alpr_zone():
    spec = ALPRRuntime._spec_from_payload(
        {
            "stream_id": "cam-214",
            "rtsp_url": "rtsp://go2rtc:8554/cam-214-hd",
            "roi_config": {"alpr_zone": {"x1": 1700, "y1": 900, "x2": 2800, "y2": 1520}},
        }
    )
    assert spec is not None
    assert spec.crop == (1700, 900, 2800, 1520)
