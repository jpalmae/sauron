# Evidencia, onboarding y entrega operacional

## Evidencia visual de eventos

Cada réplica DeepStream mantiene segmentos de video codificado sin realizar una segunda
decodificación GPU. La configuración predeterminada conserva 120 segundos por cámara y,
ante un evento, genera:

- snapshot JPEG anotado con tipo de evento, regla, hora, clase, confianza e ID;
- clip MP4 con 5 segundos previos y 10 segundos posteriores;
- actualización asíncrona del evento y del dashboard después de subir ambos objetos a S3.

El evento se publica antes de generar el clip. Si el almacenamiento o FFmpeg falla, la
alerta permanece disponible con `evidence_status=partial` o sin evidencia; el hilo de
metadata DeepStream nunca espera disco o red.

Variables principales:

```text
EVIDENCE_ENABLED=true
EVIDENCE_PRE_SECONDS=5
EVIDENCE_POST_SECONDS=10
EVIDENCE_RETENTION_SECONDS=120
S3_RETENTION_DAYS=90
```

Prometheus expone `sauron_deepstream_evidence_total{status=...}` para `queued`, `uploaded`,
`failed`, `queue_full` y `clip_oversize`.

## Onboarding de cámaras

Antes de activar una cámara, la interfaz exige una prueba satisfactoria. La cámara también
puede guardarse inactiva para preparar instalaciones que todavía no tienen conectividad.
La prueba valida RTSP/RTSPS/HLS/HTTP y devuelve codec, resolución, FPS, formato de pixel,
bitrate, latencia y un frame de preview. El resultado se persiste para formar el checklist:

1. video probado;
2. ROI configurada;
3. cámara activada.

“Descubrir ONVIF” envía WS-Discovery desde la red del contenedor API. Si la red bloquea
multicast UDP 239.255.255.250:3702, el alta manual por RTSP continúa disponible. ONVIF
descubre host/nombre/ubicación; el operador debe completar la ruta RTSP y credenciales del
fabricante, que después se validan sin aparecer en logs de aplicación.

## Notificaciones confiables

Webhook, Telegram y SMTP usan una tabla outbox. El consumidor del evento sólo encola la
entrega; un worker independiente espera brevemente la evidencia y luego entrega. Cada
canal configura:

- prioridad mínima;
- cooldown de deduplicación;
- cantidad máxima de intentos;
- filtro opcional por cámara.

Los reintentos usan backoff exponencial y quedan visibles como `pending`, `retry`, `sent`,
`failed` o `cancelled`. Los errores del proveedor se conservan sin exponer contraseñas o
tokens en la API.

## Reportes programados

La pantalla Notificaciones permite crear reportes diarios, semanales o mensuales, elegir
hora, zona horaria y canal. El scheduler produce CSV UTF-8 de eventos, lo almacena en S3 y
encola una entrega con enlace temporal. Semanal se ejecuta los lunes y mensual el primer
día del mes.

## Recuperación

- Los segmentos previos son efímeros y se regeneran después de reiniciar DeepStream.
- Snapshots, clips y reportes terminados permanecen en S3 según su lifecycle.
- El outbox persiste reinicios del API; sólo se marca `sent` después de una respuesta
  satisfactoria del proveedor.
- Para revisar fallos use `GET /api/v1/notification-deliveries?status=failed`.
