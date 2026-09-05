# Sauron FastALPR

Servicio independiente para detección y lectura de matrículas. Consume snapshots de los
streams existentes en go2rtc, ejecuta FastALPR con ONNX Runtime y publica eventos `ALPR`
en la API de Sauron.

FastALPR, fast-plate-ocr y open-image-models usan licencia MIT. Ultralytics no es una
dependencia de este servicio.

## Inicio

```bash
docker compose --profile alpr up -d --build alpr
curl http://localhost:8091/healthz
```

Dashboard: `http://localhost:8091`. Si `ADMIN_EMAIL` y `ADMIN_PASSWORD` están definidos,
el navegador solicitará esas credenciales mediante HTTP Basic.

La web de Sauron también lo integra en `/alpr` (página "Matrículas"): nginx valida el
JWT de Sauron y añade `ALPR_BASIC_TOKEN` (base64 de `usuario:contraseña`) automáticamente.

Los streams aceptan alias `camera_id=go2rtc_source`:

```dotenv
ALPR_STREAMS=cam-10,cam-166=cam-166-hd,cam-39=cam-39-hd
ALPR_GPU_DEVICE=0
ALPR_TARGET_FPS=2
ALPR_STALE_AFTER_S=30
ALPR_PORT=8091
```

La detección no compensa una toma inadecuada. Para OCR confiable, la cámara debe mirar
al carril de acceso, evitar ángulos extremos y entregar placas de aproximadamente 80 px

## Captura

El servicio consume `rtsp://go2rtc:8554/{source}` (remux barato, ~30 fps) y muestrea a
`SAURON_ALPR_TARGET_FPS` para inferencia. El endpoint `frame.jpeg` de go2rtc rinde
<=0.5 fps y no se usa. Los eventos ALPR entran a Sauron por `POST /api/v1/events` y
aparecen en la página "Matrículas" del dashboard y en el feed de eventos.

Con `SAURON_ALPR_INGEST_TOKEN` configurado, el servicio sincroniza cada
`SAURON_ALPR_RECONCILE_S` con `/api/v1/cameras/active`: las cámaras con perfil
**matriculas** entran solas a Matrículas (su `rtsp_url` manda), y si cambias su perfil
o las eliminas, salen automáticamente. Las fuentes extra de `ALPR_STREAMS` que no
existen en la API (p. ej. demos o Caltrans) se mantienen como bootstrap.

## Datos del vehículo

Con `SAURON_ALPR_VEHICLE_API_KEY` (gratuita en https://api.boostr.cl/patente) cada lectura
se enriquece con marca, modelo, año, tipo y motor del Registro Civil vía
`https://api.boostr.cl/vehicle/{plate}.json`, con caché de 7 días por patente. Los datos
viajan en `metadata.vehicle` del evento y se muestran al expandir una lectura. El campo
`include_owner` agrega nombre/RUT del propietario (desactivado por privacidad por defecto).
