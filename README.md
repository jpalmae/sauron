# Sauron — Video Analytics Platform

Analítica de video en tiempo real para HPE GreenLake sobre NVIDIA DeepStream:
ingesta multi-canal → TrafficCamNet (TAO/TensorRT) → tracking NvDCF →
VehicleTypeNet (TAO/TensorRT) → reglas, alertas, KPIs y reportería.

## Arquitectura

```
[RTSP/HLS] → [DeepStream] ──Redis Stream──> [API] ──> [TimescaleDB]
             NVDEC + TAO                    FastAPI       └─ WS ─> [dashboard]
             NvDCF + TensorRT
```

- `deepstream/` — plano de video (Service Maker, TrafficCamNet, VehicleTypeNet, NvDCF)
- `inference/` — implementación histórica, excluida de la imagen y del runtime DeepStream
- `api/` — FastAPI async: cámaras, eventos, KPIs, reportes CSV, branding, WebSocket
- `web/` — dashboard React (Vite + Tailwind v4 + Recharts), white-label
- `deploy/` — Dockerfiles, Helm chart, prometheus.yml, mediamtx.yml

## Quickstart GPU

```bash
cp .env.example .env
docker compose -f docker-compose.yml -f docker-compose.deepstream.yml \
  --profile gpu up -d --build
```

Login: `ADMIN_EMAIL` / `ADMIN_PASSWORD` del `.env` (admin bootstrap en el primer arranque).

La imagen oficial de DeepStream incluye los modelos TAO. En el primer arranque
se compilan motores FP16 específicos para la GPU y el tamaño de lote; el
volumen `deepstream-engines` los conserva para reinicios posteriores.

## Autenticación

JWT con roles (`admin` escribe, `viewer` lee). `SAURON_AUTH_ENABLED=true` en
compose. Endpoints públicos: `/healthz`, `/api/v1/branding` (para la página de
login). La ingesta directa (`POST /api/v1/events`) acepta `SAURON_INGEST_TOKEN`
o JWT de admin; la vía Redis es interna al cluster. El WS usa `?token=`.
Crear usuarios: tabla `users` (hash argon2) — endpoint de gestión en backlog.

## Modelos NVIDIA

- `TrafficCamNet` detecta `car`, `bicycle`, `person` y `road_sign`.
- `VehicleTypeNet` clasifica vehículos en `coupe`, `largevehicle`, `sedan`,
  `suv`, `truck` y `van`.
- `NvDCF` mantiene identidades y trayectorias en GPU.

## Calibración

**Velocidad (homografía)**: en el dashboard → Cámaras → ROI → herramienta
*Homografía*: marca 4 esquinas de un rectángulo del plano calzada e ingresa sus
medidas reales en metros (ancho/alto). La velocidad se calcula como
`|Δmundo| / Δt · 3.6` km/h por track.

**Líneas de conteo**: herramienta *Línea* (2 clicks); la dirección forward se
define con la herramienta *Dirección* (click hacia el flujo).

## Pruebas de carga y métricas

```bash
curl http://localhost:9100/healthz
curl http://localhost:9100/metrics
nvidia-smi
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

## Features P2 (avanzado)

- **Privacidad**: `roi.privacy.blur_faces/blur_plates` → redacción (blur) en
  snapshots y clips antes de persistir (Ley 19.628 / GDPR).
- **ReID multi-cámara / tiempo de viaje**: firmas HSV en cada `LINE_CROSSING`;
  la API matchea contra cruces recientes de la cámara upstream del corredor
  (`/api/v1/corridors`) → evento `TRAVEL_TIME` con `travel_time_s` y
  `avg_speed_kmh`. Verificado en vivo: 300 s / 96 km/h.
- **PTZ autotracking**: `stream.ptz` (ONVIF) — sigue el objeto de eventos
  críticos por N segundos y vuelve al preset; cooldown anti-oscilación.
- **Audio analytics**: `stream.audio.enabled` — tap PCM vía ffmpeg, detector
  de picos RMS sobre baseline → `AUDIO_ANOMALY`.
- **Loop de mejora**: feedback por evento (✓/falso positivo en la GUI) y
  exportación de evidencia para recalibrar o reentrenar modelos TAO.
- **HA active/standby**: `SAURON_HA_ENABLED=true` + N réplicas de inference —
  leader election por Redis (TTL 15s), takeover automático.

## Features P0 (operación)

- **Notificaciones multicanal**: webhook / Telegram / email por canal con
  prioridad mínima y filtro por cámara. CRUD + botón de prueba en
  *Notificaciones*. Los secretos quedan enmascarados en la API.
- **Salud de cámara**: `CAMERA_OFFLINE`/`CAMERA_ONLINE` automáticos si un
  stream deja de producir frames (`SAURON_CAMERA_OFFLINE_S`, default 60s).
- **Retención**: TimescaleDB `add_retention_policy` en `analytics_events`
  (`SAURON_RETENTION_DAYS`) + lifecycle MinIO de evidencia
  (`SAURON_S3_RETENTION_DAYS`). 0 = desactivado.
- **SSO (MS365 / Google Workspace)**: Authorization Code + discovery + JWKS.
  Configurar en `.env`:
  ```
  OIDC_PROVIDERS_JSON={"microsoft":{"issuer":"https://login.microsoftonline.com/<tenant>/v2.0","client_id":"...","client_secret":"..."},"google":{"issuer":"https://accounts.google.com","client_id":"...","client_secret":"..."}}
  OIDC_REDIRECT_BASE=https://tu-dominio
  OIDC_ALLOWED_DOMAINS=empresa.com
  ```
  App registration MS365: redirect URI `<OIDC_REDIRECT_BASE>/api/v1/auth/oidc/callback`.
  El primer usuario SSO queda admin si no hay usuarios; el resto viewer.

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
