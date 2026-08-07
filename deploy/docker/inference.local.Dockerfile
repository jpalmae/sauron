# syntax=docker/dockerfile:1
#
# Local/dev inference image: CPU-only, no CUDA/TensorRT (runs on ARM64 Macs).
# Uses detector.backend=mock or openai. For the GPU image see inference.Dockerfile.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates ffmpeg libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:/opt/venv/bin:$PATH"

COPY inference/pyproject.toml ./
COPY inference/src ./src
RUN uv venv /opt/venv && uv pip install --python /opt/venv/bin/python -e ".[live]"

COPY inference/tools ./tools
# Baked model catalog (ONNX CPU): everything works offline out of the box.
COPY inference/models/ /app/models/

VOLUME ["/app/configs"]
EXPOSE 9100
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:9100/healthz')"

ENTRYPOINT ["sauron-inference"]
CMD ["run", "-c", "configs/pipeline.local.yaml"]
