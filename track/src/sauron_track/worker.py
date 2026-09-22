"""TrackWorker: Ultralytics track() con persist=True por camara.

Sustituye el rol de DeepStream para las camaras asignadas:
- deteccion multi-clase COCO (person, bicycle, car, motorcycle, bus, truck, dog)
- ByteTrack: identidad estable entre frames (track_id persistente)
- publica el mismo esquema de cache que consume el overlay
- cruces por linea (L1) con direccion y cooldown por track
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
import urllib.request
from typing import Any

import cv2
import httpx
import numpy as np

log = logging.getLogger(__name__)


def _segments_cross(p: tuple[float, float], c: tuple[float, float],
                    a: tuple[float, float], b: tuple[float, float]) -> bool:
    def ccw(A, B, C):
        return (C[1]-B[1])*(A[0]-B[0]) - (A[1]-B[1])*(C[0]-B[0])
    d1 = ccw(a, b, p)
    d2 = ccw(a, b, c)
    if d1 == 0 or d2 == 0:
        return False
    return d1 > 0 != d2 > 0


class TrackWorker:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._model = None
        self._model_error: str | None = None
        self._camera_uuid: dict[str, str] = {}
        self._http = httpx.Client(timeout=15)
        self._prev_centers: dict[str, tuple[float, float]] = {}
        self._counted: set[tuple[str, str]] = set()
        self._last_event: dict[str, float] = {}
        self._lines: dict[str, list[dict]] = {}
        self.stats: dict[str, Any] = {"frames": 0, "tracks": 0, "crossings": 0, "events": 0}

    def start(self) -> None:
        log.info("trackdbg-start: iniciando worker, camaras=%s", self.settings.cameras)
        for stream in self.settings.cameras:
            t = threading.Thread(
                target=self._camera_loop, args=(stream,), name=f"track-{stream}", daemon=True
            )
            t.start()
            self._threads.append(t)
        t = threading.Thread(
            target=self._refresh_loop, name="track-cams", daemon=True
        )
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()

    # -- infra -------------------------------------------------------------
    def _refresh_loop(self) -> None:
        while not self._stop.is_set():
            try:
                r = self._http.get(
                    f"{self.settings.api_url}/cameras/active",
                    headers={"Authorization": f"Bearer {self.settings.ingest_token}"},
                )
                r.raise_for_status()
                items = r.json()
                if isinstance(items, dict):
                    items = items.get("items", items.get("cameras", []))
                for c in items:
                    sid, cid = c.get("stream_id"), c.get("id")
                    if sid and cid and sid in self.settings.cameras:
                        self._camera_uuid[sid] = cid
            except Exception:
                log.exception("camera refresh fallo")
            self._stop.wait(60)

    def _model(self):
        if self._model is None:
            from ultralytics import YOLO

            self._model = YOLO(self.settings.model_name)
            log.info("modelo %s cargado", self.settings.model_name)
        return self._model

    # -- captura + seguimiento --------------------------------------------
    def _camera_loop(self, stream: str) -> None:
        log.info("trackdbg-loop cam=%s arranca", stream)
        import redis as redis_lib

        redis_client = redis_lib.Redis.from_url(self.settings.redis_url, decode_responses=True)
        model = self._model()
        fetch_url = f"{self.settings.go2rtc_api}/api/frame.jpeg?src={stream}"
        while not self._stop.is_set():
            try:
                log.info("trackdbg fetch %s", fetch_url)
                req = urllib.request.urlopen(fetch_url, timeout=8)
                arr = np.frombuffer(req.read(), np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            except Exception:
                frame = None
            if frame is None:
                self._stop.wait(1.0)
                continue
            h, w = frame.shape[:2]
            self.stats["frames"] = self.stats.get("frames", 0) + 1

            results = model.track(frame, persist=True, conf=self.settings.conf,
                                  iou=self.settings.iou, classes=self.settings.classes,
                                  verbose=False)
            tracks = []
            r = results[0] if results else None
            if r is not None and r.boxes is not None and len(r.boxes):
                ids = r.boxes.id
                for i in range(len(r.boxes)):
                    tid = int(ids[i]) if ids is not None else None
                    if tid is None:
                        continue
                    x1, y1, x2, y2 = [float(v) for v in r.boxes.xyxy[i]]
                    cls_id = int(r.boxes.cls[i])
                    cls_name = model.names.get(cls_id, str(cls_id)) if hasattr(model, "names") else str(cls_id)
                    conf = float(r.boxes.conf[i])
                    tracks.append({"id": tid, "class": cls_name, "conf": conf,
                                   "box": [x1 / w, y1 / h, x2 / w, y2 / h]})
                    cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
                    self._check_crossing(stream, tid, cls_name, (cx, cy),
                                         (x1 / w, y1 / h, x2 / w, y2 / h),
                                         conf, frame, redis_client)
            self.stats["tracks"] = self.stats.get("tracks", 0) + len(tracks)

            # publicar cache de detecciones (mismo esquema que DeepStream)
            payload = {
                "ts": time.time(),
                "frame_seq": self.stats["frames"],
                "width": 1280,
                "height": 720,
                "objects": [
                    {
                        "id": t["id"],
                        "class": t["class"],
                        "confidence": t["conf"],
                        "vehicle_type": None,
                        "box": t["box"],
                    }
                    for t in tracks
                ],
            }
            redis_client.set(f"sauron:detections:{stream}", json.dumps(payload))
            self._stop.wait(max(0.05, 1.0 / self.settings.target_fps))

    def _check_crossing(self, stream, tid, cls_name, center, box, conf, frame, redis_client):
        lines = self._lines.get(stream) or self._load_lines(stream, redis_client)
        for line in lines:
            key = (line["id"], str(tid))
            a, b = line["points"]
            prev = self._prev_centers.get(str(tid))
            cur = center
            if prev is None:
                self._prev_centers[str(tid)] = cur
                continue
            def ccw(A, B, C):
                return (C[1]-B[1])*(A[0]-B[0]) - (A[1]-B[1])*(C[0]-B[0])
            crossed = (ccw(a, b, prev) > 0) != (ccw(a, b, cur) > 0)
            self._prev_centers[str(tid)] = cur
            if not crossed:
                continue
            if self._last_event.get(key) and time.time() - self._last_event[key] < 2.0:
                continue
            self._last_event[key] = time.time()
            direction = "forward" if (cur[0] - prev[0]) >= 0 else "reverse"
            self._emit_crossing(stream, line["id"], str(tid), cls_name, direction, conf, frame)

    def _load_lines(self, stream, redis_client):
        try:
            raw = redis_client.get("sauron:track:lines:" + stream)
            if raw:
                self._lines[stream] = json.loads(raw)
        except Exception:
            log.exception("lineas fallo")
        return self._lines.get(stream, [])

    def _emit_crossing(self, stream, line_id, track_id, cls_name, direction, conf, frame):
        camera_id = stream
        jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
        payload = {
            "event_type": "LINE_CROSSING",
            "camera_id": camera_id,
            "timestamp": time.time(),
            "confidence": conf,
            "priority": "info",
            "rule_id": "ultralytics-track",
            "metadata": {
                "line_id": line_id,
                "vehicle_class": cls_name,
                "direction": direction,
                "track_id": track_id,
            },
            "snapshot_jpeg": base64.b64encode(jpeg).decode("ascii"),
        }
        try:
            r = self._http.post(
                f"{self.settings.api_url}/events",
                json=payload,
                headers={"Authorization": f"Bearer {self.settings.ingest_token}"},
            )
            r.raise_for_status()
            self.stats["events"] = self.stats.get("events", 0) + 1
            log.info("cruce %s %s dir=%s emitido [%s]", line_id, cls_name, direction, stream)
        except Exception:
            log.exception("fallo al emitir cruce")

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok" if self._model is not None else "loading",
            "model_error": self._model_error,
            "model": self.settings.model_name,
            "device": f"cuda:{self.settings.device}",
            "cameras": [
                {
                    "stream": s,
                    "frames": self.stats.get("frames", 0),
                    "tracks": self.stats.get("tracks", 0),
                    "events": self.stats.get("events", 0),
                }
                for s in self.settings.cameras
            ],
        }
