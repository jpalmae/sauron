# syntax=docker/dockerfile:1
#
# Sauron inference service: multi-stream RTSP -> TensorRT YOLOv8 -> ByteTrack -> Rules.
#
# Build (on the x86_64 GPU host or CI with buildx):
#   docker build -f deploy/docker/inference.Dockerfile -t sauron/inference:0.1.0 .
# Run:
#   docker run --gpus all -v $PWD/inference/configs:/app/configs:ro \
#     sauron/inference:0.1.0 run -c configs/pipeline.yaml
#
# Base image: CUDA 12.4 runtime on Ubuntu 22.04. TensorRT/cuda-python come from
# PyPI wheels (installed below), so no devel toolkit is needed at runtime.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# Python 3.11 (deadsnakes) + GStreamer (RTSP/NVDEC path) + FFmpeg fallback decode.
RUN apt-get update \
    && apt-get install -y --no-install-recommends software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-dev \
        curl ca-certificates \
        gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-libav \
        libglib2.0-0 libgl1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:/opt/venv/bin:$PATH"

WORKDIR /app

# Dependencies (incl. GPU extras: tensorrt + cuda-python wheels).
COPY inference/pyproject.toml ./
COPY inference/src ./src
RUN uv venv /opt/venv --python 3.11 \
    && uv pip install --python /opt/venv/bin/python -e ".[gpu]"

COPY inference/tools ./tools
# Model catalog baked into the image (see tools/export_models.py); engines are
# host-specific and built on first boot into the models volume.
COPY inference/models/ /app/models-baked/

# TensorRT engines are architecture-specific: mount or copy per-host builds.
VOLUME ["/app/models", "/app/configs"]

ENTRYPOINT ["sh", "-c", "python tools/ensure_models.py ${ENSURE_ARGS:--c configs/pipeline.yaml} && exec sauron-inference \"$@\"", "sh"]
CMD ["run", "-c", "configs/pipeline.yaml"]
