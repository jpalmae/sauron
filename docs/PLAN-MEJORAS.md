# Plan de mejoras Sauron — Estabilidad · Performance · Detección

## 1. Estabilidad (prioridad alta)

| # | Mejora | Problema que resuelve | Esfuerzo |
|---|--------|----------------------|----------|
| 1.1 | **Healthcheck real de deepstream**: el healthcheck actual ejecuta `/opt/sauron/bin/python` que no existe en el contenedor → siempre "unhealthy" y enmascara fallos reales. Apuntarlo a `/opt/venv/bin/python` o wget | Monitoreo confiable; poder alertar de caídas reales | Bajo |
| 1.2 | **Watchdog de fuentes RTSP**: si una cámara queda `offline` con reintentos agotados (caso cam-43: 15 h caída sin recovery), el controller debe re-agendar su captura con backoff exponencial, indefinidamente | Cámaras que no vuelven solas tras un corte | Medio |
| 1.3 | **Recarga de ROI sin reinicio**: el reconciler ignora cambios de `roi_config` de cámaras ya activas; hoy exige reiniciar deepstream al editar líneas | Ediciones de líneas/límites aplican en ~15 s | Medio |
| 1.4 | **Arranque escalonado post-reboot**: `depends_on` + delays (infra → api → go2rtc → deepstream → alpr) para no estresar la GPU con builds concurrentes | El crash de GPU del 10-sep | Bajo |
| 1.5 | **Alertas de salud**: notificar (canal ya soportado) cuando `live_cameras < active-3`, disco > 85 %, o ALPR `attempts` congelado | Enterarse antes que el usuario | Bajo |

## 2. Performance

| # | Mejora | Detalle |
|---|--------|---------|
| 2.1 | **Caché de engines TRT por GPU** (UUID): evita rebuilds de ~6 min en cada cambio y rebuilds fallidos que tumban el servicio | Los engines se guardan hoy junto al ONNX con nombre no determinístico |
| 2.2 | **target_fps 25** ya activo; monitorear GPU ≤ 60 % con 18 cámaras. Si se agregan cámaras, priorizar profiles (matriculas/trafico a fps completo, people a 10) | Hecho parcialmente |
| 2.3 | **Balance de GPUs**: deepstream→5060 Ti, ALPR→3090 ya asignado por UUID; revisar tras el incidente que la 3090 quedó estable | Hecho |
| 2.4 | Tracker: evaluar `config_tracker_NvDCF_accuracy.yml` vs `perf` (mejor persistencia de ID = menos cruces perdidos) | Rápido de probar |

## 3. Detección en Tráfico + seguimiento (cam-119 y escalamiento)

| # | Mejora | Detalle |
|---|--------|---------|
| 3.1 | **YOLOX: construir parser correcto** para DS 9.0 (deepstream-yolo `nvdsinfer_custom_impl_Yolo`) y validar cajas contra el stream de prueba | Habilita moto, bus, camión, perro (COCO 80). Hoy TrafficCamNet solo car/bicycle/person |
| 3.2 | **Velocidad real**: calibrar homografía por cámara en el editor (soportado) → `speed_kmh` en eventos y KPI | cam-119 primera candidata |
| 3.3 | **KPIs por clase/dirección**: `hourly_kpis` ya se escribe; agregar panel Analítica con series por hora y export CSV | Ya existe base |
| 3.4 | **Dirección con semántica**: definir vector "entrada" por cámara en el editor (hoy forward/reverse es relativo) | Bajo |
| 3.5 | **Detección fina de personas** (fase 2): clasificador secundario sobre crops de `person` para silla de ruedas/cochecito/ carrito (CLIP zero-shot ya integrado en el stack) | Medio |

## 4. Datos y disco

| # | Mejora | Estado |
|---|--------|--------|
| 4.1 | Retención de evidencia 4 días (cron diario) | ✅ Hecho |
| 4.2 | Rotación de logs (50 MB ×3) | ✅ Hecho |
| 4.3 | "Lecturas recientes" con imágenes: panel ya lee de BD; imagen disponible mientras la evidencia esté dentro de retención | ✅ Verificado |
| 4.4 | Podar eventos huérfanos (snapshot_key de objetos inexistentes) en el mismo cron | Pendiente bajo |

## 5. Orden de ejecución sugerido

1. 1.1 + 1.2 (estabilidad observable) — media jornada
2. 1.3 (ROI hot-reload) — media jornada
3. 3.1 (YOLOX parser) — 1-2 días (construir + validar cajas)
4. 3.2 + 3.3 (velocidad + KPIs) — 1 día
5. 2.4 + 1.5 — refinamientos
