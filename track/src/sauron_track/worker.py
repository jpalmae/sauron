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
import select
import subprocess
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


class SpeedEstimator:
    """Velocidad via homografia (src/dst points) — mismo math que el DS."""

    def __init__(self, src_points, dst_points, ref_w=1280.0, ref_h=720.0):
        rows = []
        for (x, y), (u, v) in zip(src_points, dst_points):
            x, y = x / ref_w, y / ref_h
            rows.extend([
                [-x, -y, -1, 0, 0, 0, u * x, u * y, u],
                [0, 0, 0, -x, -y, -1, v * x, v * y, v],
            ])
        _, _, vh = np.linalg.svd(np.asarray(rows, dtype=np.float64))
        self._m = vh[-1].reshape(3, 3)
        self._last: dict[int, tuple[float, np.ndarray]] = {}

    # limites de velocidad instantanea por clase (descarta errores de proyeccion)
    MAX_KMH = {"person": 30.0, "bicycle": 45.0, "motorcycle": 90.0, "default": 110.0}

    def update(self, tid: int, t: float, pt: tuple[float, float], cls_name: str = "") -> float | None:
        p = self._m @ np.array([pt[0], pt[1], 1.0])
        if abs(p[2]) < 1e-9:
            return None
        world = p[:2] / p[2]
        prev = self._last.get(tid)
        self._last[tid] = (t, world)
        if prev is None or t - prev[0] <= 1e-3:
            return None
        v = float(np.linalg.norm(world - prev[1])) / (t - prev[0]) * 3.6
        limit = self.MAX_KMH.get(cls_name, self.MAX_KMH["default"])
        return v if v <= limit else None

    def purge(self, active: set[int]) -> None:
        for tid in set(self._last) - active:
            self._last.pop(tid, None)


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
        self._homography: dict[str, tuple[list, list]] = {}
        self._speed_est: dict[str, SpeedEstimator] = {}
        self._speeds: dict[tuple[str, int], float] = {}
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
                    homo = (c.get("roi_config") or {}).get("homography")
                    if sid in self.settings.cameras and homo:
                        src, dst = homo.get("src_points"), homo.get("dst_points")
                        if src and dst and self._homography.get(sid) != (src, dst):
                            self._homography[sid] = (src, dst)
                            self._speed_est.pop(sid, None)
                            log.info("homografia actualizada [%s]", sid)
            except Exception:
                log.exception("camera refresh fallo")
            self._stop.wait(60)

    def _ensure_model(self):
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
        model = self._ensure_model()
        src_stream = self.settings.frame_streams.get(stream, stream)
        proc = None
        buf = b""
        stale = 0
        while not self._stop.is_set():
            if proc is None or proc.poll() is not None:
                if proc is not None:
                    log.warning("pipe caido [%s]; reabriendo", src_stream)
                proc = self._open_pipe(src_stream)
                buf = b""
                if proc is None:
                    self._stop.wait(3.0)
                    continue
            frame, buf = self._read_frame(proc, buf)
            if frame is None:
                stale += 1
                if stale >= 3:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    proc = None
                    stale = 0
                self._stop.wait(0.5)
                continue
            stale = 0
            h, w = frame.shape[:2]
            self.stats["frames"] = self.stats.get("frames", 0) + 1

            results = model.track(frame, persist=True, conf=self.settings.conf,
                                  iou=self.settings.iou, classes=self.settings.classes,
                                  imgsz=self.settings.imgsz, verbose=False)
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
                    cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
                    feet = (cx, y2 / h)  # base de la caja: punto de contacto con el suelo
                    tracks.append({"id": tid, "class": cls_name, "conf": conf,
                                   "box": [x1 / w, y1 / h, x2 / w, y2 / h],
                                   "cx": cx, "cy": cy, "feet": feet})
            active_ids = {t["id"] for t in tracks}
            for t in tracks:
                spd = self._update_speed(stream, t["id"], t["feet"], t["class"])
                t["class"] = self._classify(stream, t, spd, tracks)
                self._check_crossing(stream, t["id"], t["class"], (t["cx"], t["cy"]),
                                     (t["box"][0], t["box"][1], t["box"][2], t["box"][3]),
                                     t["conf"], frame, redis_client, spd)
            est = self._speed_est.get(stream)
            if est is not None:
                est.purge(active_ids)
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

    def _open_pipe(self, src_stream: str):
        """ffmpeg con decode NVDEC: 1080p HEVC ~gratis (frame.jpeg costaba 1.6s)."""
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-hwaccel", "cuda", "-rtsp_transport", "tcp",
            "-i", f"rtsp://go2rtc:8554/{src_stream}",
            "-an", "-vf", "fps=8", "-f", "image2pipe",
            "-vcodec", "mjpeg", "-q:v", "4", "-",
        ]
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1 << 20
            )
            log.info("pipe ffmpeg abierto [%s]", src_stream)
            return proc
        except Exception:
            log.exception("no se pudo abrir ffmpeg")
            return None

    def _read_frame(self, proc, buf: bytes, timeout: float = 4.0):
        data = buf
        start = data.find(b"\xff\xd8")
        while True:
            if start >= 0:
                end = data.find(b"\xff\xd9", start + 2)
                if end >= 0:
                    jpg = data[start:end + 2]
                    rest = data[end + 2:]
                    arr = np.frombuffer(jpg, np.uint8)
                    return cv2.imdecode(arr, cv2.IMREAD_COLOR), rest
            ready, _, _ = select.select([proc.stdout], [], [], timeout)
            if not ready:
                return None, b""
            chunk = proc.stdout.read1(1 << 16)
            if not chunk:
                return None, b""
            data += chunk
            if start < 0:
                start = data.find(b"\xff\xd8")
            if len(data) > 8_000_000:
                data = data[-2_000_000:]
                start = data.find(b"\xff\xd8")

    def _update_speed(self, stream: str, tid: int, center, cls_name: str = "") -> float | None:
        est = self._speed_est.get(stream)
        if est is None:
            src_dst = self._homography.get(stream)
            if not src_dst:
                return None
            est = SpeedEstimator(src_dst[0], src_dst[1],
                                 float(self.settings.ref_width), float(self.settings.ref_height))
            self._speed_est[stream] = est
        v = est.update(tid, time.time(), center, cls_name)
        key = (stream, tid)
        if v is None:
            return self._speeds.get(key)
        ema = self._speeds.get(key)
        ema = v if ema is None else 0.6 * ema + 0.4 * v
        self._speeds[key] = ema
        return ema

    def _classify(self, stream: str, track: dict, speed: float | None, tracks: list[dict]) -> str:
        """person rapida sin bici/moto cerca = scooter electrico."""
        cls_name = track["class"]
        if cls_name != "person" or speed is None or speed < self.settings.scooter_min_kmh:
            return cls_name
        cx, cy = track["cx"], track["cy"]
        for t in tracks:
            if t["id"] == track["id"] or t["class"] not in ("bicycle", "motorcycle"):
                continue
            bx, by = t["cx"], t["cy"]
            if abs(bx - cx) < 0.10 and abs(by - cy) < 0.15:
                return cls_name
        return "scooter"

    def _check_crossing(self, stream, tid, cls_name, center, box, conf, frame, redis_client, speed=None):
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
            self._emit_crossing(stream, line["id"], str(tid), cls_name, direction, conf, frame, speed)

    def _load_lines(self, stream, redis_client):
        try:
            raw = redis_client.get("sauron:track:lines:" + stream)
            if raw:
                self._lines[stream] = json.loads(raw)
        except Exception:
            log.exception("lineas fallo")
        return self._lines.get(stream, [])

    def _emit_crossing(self, stream, line_id, track_id, cls_name, direction, conf, frame, speed=None):
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
                "speed_kmh": round(speed, 1) if speed is not None else None,
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
