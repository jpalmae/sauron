# Sauron — Video Analytics Platform

Analítica de video en tiempo real para HPE GreenLake, implementada sobre
NVIDIA DeepStream y modelos NVIDIA TAO.

## Arquitectura

```text
[RTSP/HLS] -> [DeepStream] --Redis Streams--> [FastAPI] -> [TimescaleDB]
               NVDEC                         |             +-> MinIO
               TrafficCamNet                 +-> WebSocket
               NvDCF                         +-> Dashboard React
               VehicleTypeNet
```

- `deepstream/`: plano de video GPU, fuentes dinámicas, tracking y reglas.
- `api/`: autenticación, cámaras, eventos, KPIs, alertas y reportes.
- `web/`: dashboard, video WebRTC, overlays y configuración de ROI.
- `deploy/`: imágenes, Helm, Prometheus y gateways de video.

Existe un solo runtime de analítica: DeepStream. La elección de backend o
modelo no se expone por cámara; los cambios de modelo se entregan como una
versión probada del plano de video.

## Pipeline de video

1. `nvmultiurisrcbin` agrega y retira cámaras activas desde la API.
2. TrafficCamNet detecta automóviles, bicicletas, personas y señales.
3. NvDCF mantiene IDs y trayectorias en GPU.
4. VehicleTypeNet clasifica los vehículos detectados.
5. Las reglas generan eventos y Redis desacopla el plano de video de la API.

Analíticas actuales:

- Conteo y dirección por cruce de línea.
- Clasificación de vehículos.
- Velocidad mediante homografía calibrada.
- Vehículo detenido y obstrucción.
- Sentido contrario.
- Congestión por ocupación de ROI.
- Ocupación básica de personas, sin pose ni reconocimiento biométrico.

## Inicio con GPU

```bash
cp .env.example .env
docker compose --profile gpu up -d --build
```

La imagen de DeepStream contiene los modelos TAO. Durante el primer arranque
TensorRT compila engines FP16 para la GPU y el batch configurado; el volumen
`deepstream-engines` los conserva entre recreaciones.

Puertos locales:

- Dashboard: `http://localhost:8080`
- API: `http://localhost:8000`
- Salud y métricas DeepStream: `http://localhost:9100/healthz` y `/metrics`
- go2rtc: `http://localhost:1984`

El usuario inicial proviene de `ADMIN_EMAIL` y `ADMIN_PASSWORD`. No utilice los
valores de ejemplo fuera de un entorno desechable.

## Cámaras y calibración

Las cámaras activas se reconcilian desde `GET /api/v1/cameras/active`. Cada una
tiene un perfil funcional (`traffic` o `people`), una URL RTSP/HLS y una
configuración de ROI.

En el dashboard, `Cámaras -> ROI` permite definir:

- Líneas de conteo y su dirección permitida.
- Polígonos para detención, sentido contrario, congestión u ocupación.
- Homografía mediante cuatro puntos y dimensiones reales de la calzada.

El watchdog considera una cámara estancada si deja de producir frames, intenta
recrear la fuente y finalmente reinicia el proceso nativo para permitir la
recuperación supervisada por Docker o Kubernetes.

## Perfiles XS/S/M

| Perfil | NVIDIA L4 | Máximo de streams |
| --- | ---: | ---: |
| XS | 1 | 20 |
| S | 2 | 40 |
| M | 3 | 60 |

Los perfiles S y M crean un StatefulSet con una réplica por GPU. Las cámaras se
asignan de forma determinista entre réplicas y cada una mantiene sus propios
engines TensorRT en un volumen persistente.

Estos valores son límites de configuración, no una certificación de capacidad.
Cada combinación de resolución, codec, FPS y analíticas debe superar una prueba
de carga y estabilidad antes de comprometerse comercialmente.

## Kubernetes / GreenLake

Los secretos de evaluación vienen habilitados para que `helm lint/template`
sean autocontenidos. Para producción, cree un Secret externo con las claves
`postgres-password`, `s3-secret-key`, `ingest-token`, `jwt-secret` y
`admin-password`, y desactive su creación desde values.

```bash
helm upgrade --install sauron deploy/helm/sauron \
  --set profile=xs \
  --set branding.domain=vision.cliente.com \
  --set secrets.create=false \
  --set secrets.name=sauron-secrets
```

La infraestructura incluida es apropiada para evaluación. En producción deben
usarse PostgreSQL/Timescale, Redis y almacenamiento de objetos administrados u
operados con respaldo y alta disponibilidad.

## Observabilidad

```bash
curl http://localhost:9100/healthz
curl http://localhost:9100/metrics
nvidia-smi
```

Las métricas incluyen FPS, frames, objetos, eventos, drops, estado por cámara y
recuperaciones. El objetivo operativo inicial es al menos 90 % del FPS definido
por stream y latencia de evento inferior a dos segundos.

## Mejora del modelo

Los eventos pueden marcarse como correctos o falsos positivos. La evidencia
revisada se exporta en COCO, compatible con flujos de entrenamiento NVIDIA TAO:

```text
GET /api/v1/reports/dataset-coco.zip
```

La generación de snapshots/clips desde el plano DeepStream y el entrenamiento
automatizado son trabajos posteriores; no se anuncian como capacidades activas.

## CI/CD

`.github/workflows/ci.yml` ejecuta:

- Ruff, mypy y pytest para `deepstream/` y `api/`.
- Vitest y build de producción para `web/`.
- `helm lint` y render del chart.
- Build y publicación en GHCR de `sauron-deepstream`, `sauron-api` y
  `sauron-web` después de un push válido a `main` o a un tag.

## Desarrollo

```bash
cd deepstream && uv venv && uv pip install -e ".[dev]" && pytest
cd api && uv venv && uv pip install -e ".[dev]" && pytest
cd web && npm ci && npm run test && npm run build
```

Las pruebas unitarias del plano DeepStream no requieren GPU. La ejecución real
y la compilación de engines requieren Linux, driver NVIDIA y NVIDIA Container
Toolkit.
