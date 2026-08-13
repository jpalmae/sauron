#!/bin/bash
cd ~/projects/sauron/inference
export $(grep -v "^#" ../.env | xargs)
export SAURON_REDIS_URL=redis://localhost:6379/0
export SAURON_API_URL=http://localhost:8000
export SAURON_API_INGEST_URL=http://localhost:8000
export SAURON_METRICS_PORT=9101
export SAURON_API_CAMERAS_FPS=5
export SAURON_API_CAMERAS_POLL_S=15
export SAURON_INGEST_TOKEN=$INGEST_TOKEN
exec ../.venv-gpu/bin/sauron-inference run -c configs/pipeline.local.yaml
