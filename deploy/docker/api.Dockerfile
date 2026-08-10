# syntax=docker/dockerfile:1
#
# Sauron API service (CPU-only): FastAPI + TimescaleDB + Redis consumer + MinIO.
#   docker build -f deploy/docker/api.Dockerfile -t sauron/api:0.1.0 .
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN pip install --no-cache-dir uv
ENV PATH="/opt/venv/bin:$PATH"

COPY api/pyproject.toml ./
COPY api/src ./src
RUN uv venv /opt/venv && uv pip install --python /opt/venv/bin/python -e .

COPY api/alembic.ini ./alembic.ini
COPY api/alembic ./alembic
# CLIP models for semantic search (export with tools/export_clip.py)
COPY api/models/ ./models/

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["sh", "-c", "alembic upgrade head && uvicorn sauron_api.main:app --host 0.0.0.0 --port 8000"]
