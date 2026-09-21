# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 curl git ca-certificates git ca-certificates git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# torch con CUDA primero (wheel cu121)
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu121

COPY relate/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY relate/src /app/src
ENV PYTHONPATH=/app/src

EXPOSE 8093
HEALTHCHECK --interval=20s --timeout=5s --retries=12 --start-period=10m \
    CMD curl -sf http://localhost:8093/healthz || exit 1

CMD ["python", "-m", "sauron_relate.main"]
