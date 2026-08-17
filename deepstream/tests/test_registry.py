from sauron_deepstream.registry import Camera, CameraRegistry, camera_from_api


def test_registry_binds_dynamic_source_to_camera():
    registry = CameraRegistry()
    camera = Camera("cam-1", "Acceso", "rtsp://camera", "traffic", None)
    registry.set_camera(camera)
    registry.bind_source(7, "cam-1")

    assert registry.is_bound("cam-1") is True
    assert registry.camera_for_source(7) == camera
    registry.unbind_source(7)
    assert registry.is_bound("cam-1") is False
    registry.bind_source(7, "cam-1")
    registry.remove_camera("cam-1")
    assert registry.camera_for_source(7) is None


def test_camera_from_api_validates_roi():
    camera = camera_from_api(
        {
            "stream_id": "cam-2",
            "name": "Cruce",
            "rtsp_url": "rtsp://old",
            "roi_config": {
                "lines": [{"id": "count", "points": [[0, 10], [100, 10]]}]
            },
        },
        "rtsp://resolved",
    )
    assert camera.uri == "rtsp://resolved"
    assert camera.analytics_profile == "traffic"
    assert camera.roi is not None
    assert camera.roi.lines[0].id == "count"
