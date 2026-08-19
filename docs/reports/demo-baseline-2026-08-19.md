# Baseline de videoanalítica — demo Robotito

Fecha: 2026-08-19  
Revisión desplegada: `309c216`  
Resolución de inferencia: 1280×720  
FPS objetivo: 10 por cámara

## Resultado operativo

| Cámara | Perfil | Muestras | FPS efectivo | Ratio FPS | Calibración |
| --- | --- | ---: | ---: | ---: | --- |
| caltrans-i5-43rd | Tráfico vehicular | 30 | 9,969 | 99,69% | PASS, 0 errores |
| caltrans-us50-howe | Bicicletas | 30 | 9,988 | 99,88% | PASS, 0 errores |

Ambas cámaras permanecieron en estado `live` durante la captura. La calibración conserva
una advertencia explícita por ausencia de homografía: no se reportará velocidad hasta
contar con puntos y distancias reales de la escena.

## Predicciones observadas

Estos valores describen las cajas producidas en las 30 muestras. **No representan precisión**
porque aún no se han comparado con ground truth independiente.

| Cámara | Car | Bicycle | Person |
| --- | ---: | ---: | ---: |
| caltrans-i5-43rd | 141 | 27 | 42 |
| caltrans-us50-howe | 1 | 2 | 20 |

Las ROI específicas comenzaron a emitir eventos con los identificadores nuevos:

- `vehicle-count`: cruces de automóviles en I-5.
- `bicycle-count`: cruces de bicicletas en US-50.

Los eventos históricos con regla `L1` pertenecen a la calibración anterior y no deben
mezclarse con el benchmark nuevo.

## Evidencia preparada

En `robotito`:

```text
/home/robotito/sauron-evaluations/e5b9678/
├── caltrans-i5-43rd/
│   ├── images/                       # 30 JPEG
│   ├── ground-truth.coco.json        # listo para etiquetar
│   ├── manifest.json
│   └── predictions.jsonl
└── caltrans-us50-howe/
    ├── images/                       # 30 JPEG
    ├── ground-truth.coco.json        # listo para etiquetar
    ├── manifest.json
    └── predictions.jsonl
```

Tamaño total: 6,2 MB.

## Estado de aceptación

| Métrica | Umbral piloto | Resultado |
| --- | ---: | --- |
| Precisión por cámara/clase | ≥ 0,80 | Pendiente de ground truth |
| Recall por cámara/clase | ≥ 0,80 | Pendiente de ground truth |
| Error de conteo | ≤ 10% | Pendiente de eventos etiquetados |
| FPS efectivo/objetivo | ≥ 0,90 | PASS en ambas cámaras |

El siguiente paso controlado es etiquetar las 60 imágenes en CVAT, exportar COCO Instances
y ejecutar `sauron-evaluate`. No se promoverá este baseline a evidencia comercial hasta
completar esa revisión independiente.
