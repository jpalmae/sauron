# syntax=docker/dockerfile:1
#
# Sauron API service (CPU-only): FastAPI + TimescaleDB + Redis consumer + MinIO.
#   docker build -f deploy/docker/api.Dockerfile -t sauron/api:0.1.0 .
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN curl -LsSf https://astral.sh/uv/install.sh | sh || pip install uv
ENV PATH="/root/.local/bin:/opt/venv/bin:$PATH"

COPY api/pyproject.toml ./
RUN uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python \
        "fastapi>=0.110" "uvicorn[standard]>=0.29" "sqlalchemy[asyncio]>=2.0" \
        "asyncpg>=0.29" "alembic>=1.13" "pydantic>=2.6" "pydantic-settings>=2.2" \
        "redis>=5.0" "minio>=7.2"

COPY api/src ./src
COPY api/alembic.ini ./alembic.ini
COPY api/alembic ./alembic
RUN uv pip install --python /opt/venv/bin/python --no-deps -e .

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/healthz')"

CMD ["sh", "-c", "alembic upgrade head && uvicorn sauron_api.main:app --host 0.0.0.0 --port 8000"]
