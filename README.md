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
cp .env.example .env                     # editar secretos (DB, MinIO, JWT, admin)
docker compose up -d                     # infra + api + web  → http://localhost:8080
# engine TensorRT (una vez, en el host L4):
pip install ultralytics tensorrt cuda-python
python inference/tools/build_engine.py --weights yolov8n.pt --out models/yolov8n_fp16.engine --fp16
cp inference/configs/pipeline.example.yaml inference/configs/pipeline.yaml  # editar cámaras/ROIs
docker compose --profile gpu up -d inference
docker compose --profile streaming up -d mediamtx      # live grid WebRTC (opcional)
docker compose --profile observability up -d prometheus # métricas (opcional)
```

Login: `ADMIN_EMAIL` / `ADMIN_PASSWORD` del `.env` (admin bootstrap en el primer arranque).

### Demo local sin GPU (Mac/Linux, CPU)

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml --profile local up -d --build
# dashboard en http://localhost:8080 (admin@sauron.local / admin123 con el .env de demo)
```

La demo levanta 3 cámaras preconfiguradas (seed): 2 sintéticas (conteo y
congestión garantizados) y **Shinjuku Live** — cámara pública de tráfico en
Tokio vía YouTube Live (prefijo `yt:` en `source`; yt-dlp resuelve y refresca
el manifiesto HLS solo) con detección real ONNX en CPU (`detector.backend:
onnx`, yolov8n en `inference/models/`, ~35 ms/frame).

### Backends de detección

`detector.backend` en `pipeline.yaml` (global o por stream):

| backend | uso |
|---|---|
| `tensorrt` | GPU local, 10–15 FPS/stream (default, producción L4) |
| `onnx` | CPU via OpenCV DNN, sin deps extra — demos/desarrollo (~5–15 FPS) |
| `openai` | endpoint OpenAI-compatible (vLLM, Ollama, OpenAI): `base_url` + `model`; key vía env `OPENAI_API_KEY` |
| `mock` | CI/desarrollo |

## Autenticación

JWT con roles (`admin` escribe, `viewer` lee). `SAURON_AUTH_ENABLED=true` en
compose. Endpoints públicos: `/healthz`, `/api/v1/branding` (para la página de
login). La ingesta directa (`POST /api/v1/events`) acepta `SAURON_INGEST_TOKEN`
o JWT de admin; la vía Redis es interna al cluster. El WS usa `?token=`.
Crear usuarios: tabla `users` (hash argon2) — endpoint de gestión en backlog.

## Inferencia local o remota

Tabla de backends arriba. Fuentes soportadas: `rtsp://`, archivos de video,
`synthetic` y `yt:<youtube-watch-url>` (cámaras live públicas; extra `live`).

## Modelos de detección

Catálogo horneado en las imágenes (sin descargas en runtime): **yolov8n/s/m**
y **yolo11n/s**. Selección en `pipeline.yaml`:

```yaml
defaults:
  model: yolov8n        # global
streams:
  - id: cam-01
    model: yolo11s      # override por stream
```

- Backend `onnx` (CPU): usa el `.onnx` del catálogo directamente.
- Backend `tensorrt` (GPU L4): `ensure_models` construye el `.engine` FP16 del
  modelo elegido en el primer arranque del host (volumen `models`).
- Regenerar el catálogo: `python inference/tools/export_models.py`
  (requiere ultralytics; en CI corre automático antes del build con cache).

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

## ONVIF (descubrimiento de cámaras)

```bash
pip install -e "inference[onvif]"
python inference/tools/onvif_discover.py --user admin --password secret
# imprime un bloque streams: listo para pipeline.yaml
```

## Features P1 (nivel mercado)

- **ALPR (patentes)**: `roi.alpr.enabled: true` en el ROI de la cámara + opcional
  `watchlist: [ABC123]` → evento `ALPR` / `ALPR_WATCHLIST` (crítico). OCR local
  (tesseract, en las imágenes) o VLM (`backend: vlm`).
- **Búsqueda semántica (CLIP)**: página *Búsqueda* — "camión rojo", "persona
  caída"… Embeddings CLIP ViT-B/32 ONNX CPU generados al ingerir snapshots
  (pgvector). Regenerar modelos: `python api/tools/export_clip.py`.
- **Mapa GIS**: página *Mapa* (react-leaflet + OSM) con estado por cámara;
  `latitude/longitude` editables en Cámaras.
- **Push PWA**: campana en el panel de alertas → notificaciones push nativas
  para warning/critical (service worker + Web Push VAPID).
- **OTA de modelos**: selects *Backend / Modelo* por cámara en Cámaras
  (rollout sin tocar YAML; reconcile lo levanta en caliente).
- **Sinopsis**: botón *Resumen* en Eventos → contact sheet JPEG de snapshots
  (ventana configurable), `GET /api/v1/reports/synopsis.jpg`.

## CI/CD

`.github/workflows/ci.yml`: pytest+ruff+mypy (inference, api), vitest+build
(web), helm lint, y build/push de imágenes a GHCR (`ghcr.io/<owner>/sauron-*`)
en push a main/tags. Imágenes api/web multi-arch (amd64+arm64); inference amd64.

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
