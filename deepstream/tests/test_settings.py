from pathlib import Path

from sauron_deepstream.settings import Settings


def test_renders_batch_specific_pgie_config(tmp_path: Path):
    primary_template = tmp_path / "primary.ini"
    primary_template.write_text("batch={batch_size}\nengine={engine_path}\nmodel={model_path}\n")
    secondary_template = tmp_path / "secondary.ini"
    secondary_template.write_text(
        "batch={batch_size}\nengine={engine_path}\nmodel={model_path}\nlabels={labels_path}\n"
    )
    primary_labels = tmp_path / "primary-labels.txt"
    primary_labels.write_text("car\n")
    vehicle_labels = tmp_path / "vehicle-labels.txt"
    vehicle_labels.write_text("coupe;truck\n")
    primary_model = tmp_path / "trafficcamnet.onnx"
    vehicle_model = tmp_path / "vehicletypenet.onnx"
    tracker_config = tmp_path / "tracker.yml"
    tracker_library = tmp_path / "tracker.so"
    for path in (primary_model, vehicle_model, tracker_config, tracker_library):
        path.touch()

    settings = Settings(
        api_url="http://api",
        ingest_token="token",
        redis_url="redis://redis",
        max_streams=20,
        secondary_batch_size=64,
        target_fps=10,
        inference_interval=0,
        source_poll_seconds=15,
        source_stale_seconds=45,
        source_recovery_cooldown=45,
        source_recovery_attempts=3,
        source_rest_port=9010,
        health_port=9100,
        mux_width=1280,
        mux_height=720,
        gpu_id=0,
        primary_model_path=primary_model,
        primary_labels_path=primary_labels,
        vehicle_model_path=vehicle_model,
        vehicle_labels_path=vehicle_labels,
        engine_dir=tmp_path / "engines",
        pgie_template=primary_template,
        sgie_template=secondary_template,
        tracker_config=tracker_config,
        tracker_library=tracker_library,
    )

    settings.validate_files()
    primary_output, secondary_output = settings.render_infer_configs()
    primary = primary_output.read_text()
    secondary = secondary_output.read_text()
    assert "batch=20" in primary
    assert "trafficcamnet.onnx_b20_gpu0_fp16.engine" in primary
    assert "batch=64" in secondary
    assert "vehicletypenet.onnx_b64_gpu0_fp16.engine" in secondary
