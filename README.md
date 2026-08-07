# Sauron — Video Analytics Platform

Analítica de video en tiempo real para HPE GreenLake (edge GPU NVIDIA L4):
ingesta multi-canal RTSP → detección YOLOv8 (TensorRT) → tracking ByteTrack →
reglas espacio-temporales → alertas en vivo, KPIs y reportería.

## Arquitectura

```
[RTSP cams] → [inference] ──eventos──> [Redis] ──> [api consumer] ──> [TimescaleDB]
  GPU L4        TensorRT+ByteTrack        pub/sub       FastAPI    ├─> [MinIO] snapshots/clips
              rules engine + clips MP4                    └─ WS /ws/alerts ─> [web dashboard]
```

- `inference/` — pipeline de video (Python 3.11, TensorRT, GStreamer/NVDEC, ByteTrack, rules, clips)
- `api/` — FastAPI async: cámaras, eventos, KPIs, reportes CSV, branding, WebSocket
- `web/` — dashboard React (Vite + Tailwind v4 + Recharts), white-label
- `deploy/` — Dockerfiles, Helm chart, prometheus.yml, mediamtx.yml

## Quickstart (host GPU)

```bash
cp .env.example .env                     # editar secretos
docker compose up -d                     # infra + api + web  → http://localhost:8080
# engine TensorRT (una vez, en el host L4):
pip install ultralytics tensorrt cuda-python
python inference/tools/build_engine.py --weights yolov8n.pt --out models/yolov8n_fp16.engine --fp16
cp inference/configs/pipeline.example.yaml inference/configs/pipeline.yaml  # editar cámaras/ROIs
docker compose --profile gpu up -d inference
docker compose --profile streaming up -d mediamtx      # live grid WebRTC (opcional)
docker compose --profile observability up -d prometheus # métricas (opcional)
```

## Inferencia local o remota

`detector.backend` en `pipeline.yaml` (global o por stream):

| backend | uso |
|---|---|
| `tensorrt` | GPU local, 10–15 FPS/stream (default) |
| `openai` | endpoint OpenAI-compatible (vLLM, Ollama, OpenAI): `base_url` + `model`; key vía env `OPENAI_API_KEY` |
| `mock` | CI/desarrollo |

## Calibración

**Velocidad (homografía)**: en el dashboard → Cámaras → ROI → herramienta
*Homografía*: marca 4 esquinas de un rectángulo del plano calzada e ingresa sus
medidas reales en metros (ancho/alto). La velocidad se calcula como
`|Δmundo| / Δt · 3.6` km/h por track.

**Líneas de conteo**: herramienta *Línea* (2 clicks); la dirección forward se
define con la herramienta *Dirección* (click hacia el flujo).

**INT8** (mayor throughput, requiere ~500 frames de producción):
```bash
python inference/tools/build_engine.py --weights yolov8n.pt --out models/yolov8n_int8.engine --int8 --calib-data /data/calib
```

## Pruebas de carga y métricas

```bash
python inference/tools/load_test.py --streams 20 --fps 15 --duration 60   # XS
```
Targets: ≥90% del FPS objetivo por stream, latencia de alerta < 2 s.

Métricas Prometheus: inference `:9100/metrics` (fps, drops, tracks, eventos,
latencia por cámara), api `:8000/metrics` (requests, latencias, eventos
ingeridos). Scrape config en `deploy/prometheus.yml`.

## Kubernetes (GreenLake)

```bash
helm install sauron deploy/helm/sauron \
  --set profile=s --set inference.gpus=2 \
  --set branding.appName="Mi Cliente" --set branding.domain=vision.cliente.com
```
La infra embebida (TimescaleDB/Redis/MinIO) es para evaluación; en producción
usar operadores (CloudNativePG, etc.) vía valores.

## White-label

Sin rebuild: montar logos en `./brand` (compose) y definir env
`SAURON_BRANDING_*` (app name, colores). El frontend consume
`GET /api/v1/branding` antes del primer render.

## Desarrollo

```bash
cd inference && uv venv && uv pip install -e ".[dev]" && pytest
cd api && uv venv && uv pip install -e ".[dev]" && pytest
cd web && npm install && npm run dev      # proxy a :8000
```
