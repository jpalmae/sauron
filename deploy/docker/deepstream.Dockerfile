# syntax=docker/dockerfile:1
FROM nvcr.io/nvidia/deepstream:9.0-triton-multiarch

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,video,utility \
    PATH=/opt/sauron/bin:$PATH

# Add the codecs intentionally omitted from the runtime image (notably HLS)
# and repair the GStreamer plugins using NVIDIA's bundled installer.
RUN /opt/nvidia/deepstream/deepstream/user_additional_install.sh \
    && apt-get install -y --no-install-recommends ffmpeg python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY deepstream/pyproject.toml /app/deepstream/pyproject.toml
COPY deepstream/src /app/deepstream/src

RUN python3 -m venv --system-site-packages /opt/sauron \
    && /opt/sauron/bin/pip install --no-cache-dir \
        /opt/nvidia/deepstream/deepstream/service-maker/python/pyservicemaker-*.whl \
    && /opt/sauron/bin/pip install --no-cache-dir "numpy>=1.26,<2" \
    && /opt/sauron/bin/pip install --no-cache-dir /app/deepstream

COPY deepstream/configs /app/deepstream/configs

# DeepStream writes a newly built TensorRT engine beside its ONNX source.
# Seed NVIDIA's TAO models into the persistent volume at container startup so
# both the models and their GPU-specific engines survive container recreation.
RUN mkdir -p /opt/sauron/tao-seed \
    && cp /opt/nvidia/deepstream/deepstream/samples/models/Primary_Detector/resnet18_trafficcamnet_pruned.onnx \
        /opt/sauron/tao-seed/ \
    && cp /opt/nvidia/deepstream/deepstream/samples/models/Primary_Detector/labels.txt \
        /opt/sauron/tao-seed/trafficcamnet_labels.txt \
    && cp /opt/nvidia/deepstream/deepstream/samples/models/Secondary_VehicleTypes/resnet18_vehicletypenet_pruned.onnx \
        /opt/sauron/tao-seed/ \
    && cp /opt/nvidia/deepstream/deepstream/samples/models/Secondary_VehicleTypes/labels.txt \
        /opt/sauron/tao-seed/vehicletypenet_labels.txt

COPY deepstream/entrypoint.sh /usr/local/bin/sauron-deepstream-entrypoint
RUN chmod 0755 /usr/local/bin/sauron-deepstream-entrypoint

VOLUME ["/models"]
EXPOSE 9100
CMD ["/usr/local/bin/sauron-deepstream-entrypoint"]
