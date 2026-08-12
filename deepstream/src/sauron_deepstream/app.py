from __future__ import annotations

import logging
import sys

from .analytics import MetadataProcessor, make_metadata_operator
from .bridge import RedisStreamBridge
from .controller import SourceController
from .health import HealthServer
from .metrics import Metrics
from .registry import CameraRegistry
from .settings import Settings

log = logging.getLogger(__name__)


def run() -> None:
    from pyservicemaker import DynamicSourceMessage, Pipeline, Probe

    settings = Settings.from_env()
    settings.validate_files()
    pgie_config, sgie_config = settings.render_infer_configs()
    labels = [
        line.strip()
        for line in settings.primary_labels_path.read_text().splitlines()
        if line.strip()
    ]

    metrics = Metrics()
    registry = CameraRegistry()
    bridge = RedisStreamBridge(settings.redis_url, metrics)
    processor = MetadataProcessor(registry, bridge, metrics, labels, settings.target_fps)
    health = HealthServer(settings.health_port, metrics)
    controller = SourceController(
        settings.api_url,
        settings.ingest_token,
        settings.source_rest_port,
        settings.source_poll_seconds,
        settings.max_streams,
        registry,
    )

    pipeline = Pipeline("sauron-deepstream")
    pipeline.add(
        "nvmultiurisrcbin",
        "source",
        {
            "ip-address": "127.0.0.1",
            "port": settings.source_rest_port,
            "max-batch-size": settings.max_streams,
            "batched-push-timeout": int(1_000_000 / settings.target_fps),
            "width": settings.mux_width,
            "height": settings.mux_height,
            "live-source": 1,
            "drop-pipeline-eos": 1,
            # Production inputs are continuous RTSP streams. Looping finite files
            # inside nvmultiurisrcbin is unstable when sources are added through
            # its REST API; validation clips are looped by the RTSP gateway.
            "file-loop": 0,
            "async-handling": 1,
            "select-rtp-protocol": 4,
            "latency": 200,
            "rtsp-reconnect-interval": 10,
            "rtsp-reconnect-attempts": -1,
            "gpu-id": settings.gpu_id,
        },
    )
    pipeline.add(
        "nvinfer",
        "pgie",
        {"config-file-path": str(pgie_config), "batch-size": settings.max_streams},
    )
    pipeline.add(
        "nvtracker",
        "tracker",
        {
            "ll-lib-file": str(settings.tracker_library),
            "ll-config-file": str(settings.tracker_config),
            "tracker-width": 960,
            "tracker-height": 544,
            "gpu-id": settings.gpu_id,
            "display-tracking-id": 1,
        },
    )
    pipeline.add(
        "nvinfer",
        "vehicle_type",
        {
            "config-file-path": str(sgie_config),
            "batch-size": settings.secondary_batch_size,
        },
    )
    pipeline.add("fakesink", "sink", {"sync": 0, "async": 0, "qos": 0})
    pipeline.link("source", "pgie", "tracker", "vehicle_type", "sink")
    pipeline.attach("vehicle_type", Probe("sauron-metadata", make_metadata_operator(processor)))

    def on_message(message) -> None:
        if isinstance(message, DynamicSourceMessage):
            if message.source_added:
                registry.bind_source(int(message.source_id), str(message.sensor_id))
                log.info("source %s bound to %s", message.source_id, message.sensor_id)
            else:
                registry.unbind_source(int(message.source_id))
                log.info("source %s removed", message.source_id)

    bridge.start()
    health.start()
    try:
        pipeline.prepare(on_message)
        pipeline.activate()
        metrics.ready = True
        controller.start()
        log.info(
            "DeepStream active: max_streams=%d batch=%d GPU=%d",
            settings.max_streams,
            settings.max_streams,
            settings.gpu_id,
        )
        pipeline.wait()
    finally:
        metrics.ready = False
        controller.stop()
        bridge.stop()
        health.stop()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        run()
    except Exception:
        log.exception("DeepStream service failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
