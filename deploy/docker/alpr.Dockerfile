# syntax=docker/dockerfile:1
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir uv

COPY alpr/pyproject.toml ./pyproject.toml
COPY alpr/src ./src
RUN uv pip install --python /opt/venv/bin/python ".[onnx-gpu]"

EXPOSE 8091
HEALTHCHECK --interval=15s --timeout=5s --retries=12 --start-period=5m \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8091/healthz')"

CMD ["uvicorn", "sauron_alpr.main:app", "--host", "0.0.0.0", "--port", "8091"]
