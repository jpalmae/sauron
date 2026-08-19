# Calibración y evaluación de analíticas

Este flujo separa tres cosas que no deben confundirse:

1. **Predicción:** lo que produjo DeepStream.
2. **Ground truth:** anotación revisada por una persona, sin copiar las cajas del modelo.
3. **Aceptación:** umbrales acordados antes de mirar el resultado.

El evaluador mide detección por clase con matching IoU, eventos/conteos con tolerancia
temporal y FPS efectivo contra el objetivo de cada cámara. No presenta una captura visual
como si fuera una certificación estadística.

## 1. Validar la calibración de una cámara

Exporte el `roi_config` de la cámara a JSON y ejecute:

```bash
cd deepstream
.venv/bin/sauron-calibrate \
  --config camera-roi.json \
  --width 1280 \
  --height 720 \
  --output calibration-report.md \
  --json-output calibration-report.json
```

La validación detecta:

- puntos fuera del frame e identificadores duplicados;
- líneas demasiado cortas o casi paralelas a la dirección del flujo;
- polígonos degenerados o demasiado pequeños;
- reglas de sentido contrario sin vector de dirección;
- homografías ausentes o degeneradas.

Una homografía ausente es una advertencia: el conteo puede evaluarse, pero la velocidad no
debe ofrecerse como métrica calibrada.

Las ROI específicas de los dos clips públicos de demostración se conservan en
`deploy/seed/cameras.demo.json`. No deben reutilizarse con otra posición de cámara.

## 2. Capturar un paquete de evaluación

Obtenga un JWT de administrador y expóngalo sólo como variable temporal. El capturador no
acepta tokens en la línea de comandos para evitar que queden en el historial del shell.

```bash
export SAURON_TOKEN='<jwt>'
cd deepstream
.venv/bin/sauron-eval-capture \
  --camera-id cd34b0a5-7fc3-42d7-9bfb-339879e75d8a \
  --stream-id caltrans-us50-howe \
  --go2rtc-stream public-us50-howe \
  --samples 30 \
  --interval 1 \
  --target-fps 10 \
  --output evaluation/caltrans-us50-howe
unset SAURON_TOKEN
```

El directorio debe estar vacío. El comando produce:

```text
evaluation/caltrans-us50-howe/
├── images/
├── ground-truth.coco.json
├── manifest.json
└── predictions.jsonl
```

`predictions.jsonl` contiene cajas normalizadas, clase, confianza e ID de tracking. El
archivo COCO contiene las imágenes, dimensiones y categorías, pero deliberadamente parte
sin anotaciones.

## 3. Etiquetar sin contaminar el resultado

Importe `images/` y `ground-truth.coco.json` en CVAT o una herramienta compatible con COCO.
Etiquete todos los objetos visibles de las clases `car`, `bicycle`, `person` y `roadsign`,
incluyendo objetos que el modelo no detectó. Exporte **COCO Instances** conservando los
nombres de archivo.

Reglas mínimas:

- anotar todos los frames seleccionados, no sólo los fáciles;
- marcar como `ignore` objetos ambiguos sólo si la herramienta lo soporta;
- mantener un conjunto distinto para calibración y otro para aceptación final;
- registrar resolución, clima, iluminación y cámara en `manifest.json`.

Para eventos de cruce/conteo se puede agregar ground truth JSONL:

```json
{"kind":"event","camera_id":"caltrans-i5-43rd","event_type":"LINE_CROSSING","timestamp":1787100786.1,"rule_id":"L1","class":"car","direction":"forward"}
```

Las predicciones de eventos usan el mismo formato. El matching es por cámara, tipo, regla,
clase y dirección, con una tolerancia temporal configurable.

## 4. Generar el reporte

```bash
cd deepstream
.venv/bin/sauron-evaluate \
  --ground-truth evaluation/caltrans-us50-howe/ground-truth.coco.json \
  --predictions evaluation/caltrans-us50-howe/predictions.jsonl \
  --camera-id caltrans-us50-howe \
  --iou 0.50 \
  --min-confidence 0.30 \
  --min-precision 0.80 \
  --min-recall 0.80 \
  --max-count-error-pct 10 \
  --min-fps-ratio 0.90 \
  --output evaluation/caltrans-us50-howe/report.md \
  --json-output evaluation/caltrans-us50-howe/report.json
```

El proceso termina con código `0` al aprobar y `2` al fallar, por lo que puede incorporarse
a CI o a una puerta de liberación. Las cajas usan coordenadas normalizadas
`[x1, y1, x2, y2]`; COCO se convierte automáticamente desde píxeles `[x, y, width, height]`.

## Umbral inicial sugerido

| Métrica | Piloto | Producción inicial |
| --- | ---: | ---: |
| Precisión por clase | ≥ 0,80 | ≥ 0,90 |
| Recall por clase | ≥ 0,80 | ≥ 0,90 |
| Error de conteo | ≤ 10% | ≤ 5% |
| FPS efectivo/objetivo | ≥ 0,90 | ≥ 0,95 |

Los umbrales deben evaluarse por cámara y condición. Un promedio global puede ocultar una
cámara o clase deficiente.

## Alcance estadístico

Treinta frames sirven para detectar problemas evidentes de configuración, pero no para
certificar un SLA. La aceptación comercial debería usar, como mínimo, varios cientos de
objetos por clase relevante y muestras repartidas entre horarios y condiciones ambientales.
