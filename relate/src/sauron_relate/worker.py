"""RelateAnything sidecar worker: frames + DS tracks -> semantic relation events."""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from typing import Any

import os

os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000"
)

import urllib.request

import cv2
import httpx
import numpy as np

log = logging.getLogger(__name__)

DEFAULT_VOCABULARY = [
    "walking beside",
    "following",
    "approaching",
    "crossing path of",
    "standing near",
    "riding",
    "pushing",
    "pulling",
    "interacting with",
    "facing",
]


def _box_pixels(obj: dict[str, Any], w: int, h: int) -> tuple[int, int, int, int] | None:
    """Best-effort bbox: box list, x1y1x2y2 or xywh keys, absolute or normalized."""
    bx = obj.get("box")
    if isinstance(bx, (list, tuple)) and len(bx) == 4:
        try:
            x1, y1, x2, y2 = (float(v) for v in bx)
        except (TypeError, ValueError):
            return None
        if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.5:
            x1, y1, x2, y2 = x1 * w, y1 * h, x2 * w, y2 * h
        if x2 - x1 < 4 or y2 - y1 < 4:
            return None
        return int(x1), int(y1), int(x2), int(y2)
    for keys in (("x1", "y1", "x2", "y2"), ("left", "top", "right", "bottom")):
        try:
            x1, y1, x2, y2 = (float(obj[k]) for k in keys)
            break
        except (KeyError, TypeError, ValueError):
            continue
    else:
        try:
            x, y, wd, ht = (float(obj[k]) for k in ("x", "y", "w", "h"))
            x1, y1, x2, y2 = x, y, x + wd, y + ht
        except (KeyError, TypeError, ValueError):
            return None
    if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.5:
        x1, y1, x2, y2 = x1 * w, y1 * h, x2 * w, y2 * h
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    return int(x1), int(y1), int(x2), int(y2)


class RelateWorker:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._model = None
        self._model_error: str | None = None
        self._vocab: list[str] | None = None
        self._vocab_lock = threading.Lock()
        self._camera_uuid: dict[str, str] = {}
        self._http = httpx.Client(timeout=15)
        self._last_relates: dict[tuple, float] = {}
        self._streak: dict[tuple, int] = {}
        self._enabled = True
        self.stats: dict[str, Any] = {"predictions": 0, "events": 0, "frames": 0}

    # -- hilos -------------------------------------------------------------
    def start(self) -> None:
        for stream in self.settings.cameras:
            t = threading.Thread(
                target=self._camera_loop, args=(stream,), name=f"relate-{stream}", daemon=True
            )
            t.start()
            self._threads.append(t)
        t = threading.Thread(target=self._refresh_cameras_loop, name="relate-cams", daemon=True)
        t.start()
        self._threads.append(t)
        t = threading.Thread(target=self._config_loop, name="relate-config", daemon=True)
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()

    def _refresh_cameras_loop(self) -> None:
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

    def _config_loop(self) -> None:
        import redis as redis_lib

        client = redis_lib.Redis.from_url(self.settings.redis_url, decode_responses=True)
        last_raw = None
        while not self._stop.is_set():
            try:
                raw = client.get("sauron:relate:config")
                if raw and raw != last_raw:
                    cfg = json.loads(raw)
                    last_raw = raw
                    vocab = cfg.get("vocabulary")
                    if isinstance(vocab, list) and vocab:
                        self.set_vocabulary(vocab)
                    if cfg.get("fps"):
                        try:
                            self.settings.target_fps = max(0.2, float(cfg["fps"]))
                        except (TypeError, ValueError):
                            pass
                    if cfg.get("score_threshold") is not None:
                        try:
                            self.settings.score_threshold = float(cfg["score_threshold"])
                        except (TypeError, ValueError):
                            pass
                    cams = cfg.get("cameras")
                    if isinstance(cams, list) and cams:
                        self.settings.cameras = [c.strip() for c in cams if c.strip()]
                    self._enabled = bool(cfg.get("enabled", True))
                    log.info("config de relaciones aplicada")
            except Exception:
                log.exception("lectura de config de relaciones fallo")
            self._stop.wait(10)

    # -- modelo ------------------------------------------------------------
    def _ensure_model(self) -> bool:
        if self._model is not None:
            return True
        try:
            from relsgg import RelateAnything

            self._model = RelateAnything.from_pretrained(
                self.settings.model_id, device=self.settings.device
            )
            with self._vocab_lock:
                self._model.set_vocabulary(self._vocab or list(DEFAULT_VOCABULARY))
            log.info("RelateAnything cargado (%s)", self.settings.model_id)
            return True
        except Exception:
            log.exception("carga del modelo fallo")
            self._model_error = "load failed"
            self._stop.wait(30)
            return False

    def set_vocabulary(self, vocab: list[str]) -> None:
        with self._vocab_lock:
            self._vocab = [v.strip() for v in vocab if v.strip()]
            if self._model is not None and self._vocab:
                try:
                    self._model.set_vocabulary(self._vocab)
                    log.info("vocabulario actualizado: %s", self._vocab)
                except Exception:
                    log.exception("set_vocabulary fallo")

    # -- tracks ------------------------------------------------------------
    def _latest_tracks(self, stream: str, redis_client) -> tuple[list, list] | None:
        raw = redis_client.get(f"sauron:detections:{stream}")
        if not raw:
            return None
        payload = json.loads(raw)
        w = int(payload.get("width") or 1280)
        h = int(payload.get("height") or 720)
        objects = payload.get("objects") or []
        boxes, metas = [], []
        for obj in objects[:20]:
            box = _box_pixels(obj, w, h)
            if box is None:
                continue
            boxes.append(list(box))
            metas.append(
                {
                    "class": str(obj.get("class", "")),
                    "id": obj.get("id"),
                    "type": obj.get("vehicle_type") or obj.get("posture"),
                }
            )
        if len(boxes) < 2:
            return None
        return boxes, metas

    # -- emision -----------------------------------------------------------
    def _emit(
        self, stream: str, sub: dict, predicate: str, obj: dict,
        score: float, jpeg: bytes | None, ts: float,
    ) -> None:
        camera_id = stream
        payload = {
            "event_type": "RELATION",
            "camera_id": camera_id,
            "timestamp": ts,
            "confidence": min(1.0, max(0.0, score)),
            "priority": "info",
            "rule_id": "relate",
            "metadata": {
                "subject_class": sub["class"],
                "subject_id": sub["id"],
                "subject_type": sub.get("type"),
                "predicate": predicate,
                "object_class": obj["class"],
                "object_id": obj["id"],
                "object_type": obj.get("type"),
                "camera_stream": stream,
            },
        }
        if jpeg:
            payload["snapshot_jpeg"] = base64.b64encode(jpeg).decode("ascii")
        try:
            r = self._http.post(
                f"{self.settings.api_url}/events",
                json=payload,
                headers={"Authorization": f"Bearer {self.settings.ingest_token}"},
            )
            r.raise_for_status()
            self.stats["events"] = self.stats.get("events", 0) + 1
            log.info(
                "relacion %s %s -> %s (%.2f) emitida [%s]",
                sub["class"], predicate, obj["class"], score, stream,
            )
        except Exception:
            log.exception("fallo al emitir evento de relacion")

    # -- loop principal por camara (un solo hilo: captura + prediccion) -----
    def _camera_loop(self, stream: str) -> None:
        import redis as redis_lib

        redis_client = redis_lib.Redis.from_url(self.settings.redis_url, decode_responses=True)
        interval = 1.0 / max(0.2, self.settings.target_fps)
        fetch_url = f"{self.settings.go2rtc_api}/api/frame.jpeg?src={stream}"
        last_pred = 0.0
        while not self._stop.is_set():
            if not self._enabled:
                self._stop.wait(5)
                continue
            try:
                req = urllib.request.urlopen(fetch_url, timeout=8)
                arr = np.frombuffer(req.read(), np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            except Exception:
                frame = None
            if frame is None:
                self._stop.wait(1.0)
                continue
            self.stats["frames"] = self.stats.get("frames", 0) + 1
            if time.time() - last_pred < interval:
                self._stop.wait(max(0.05, interval - (time.time() - last_pred)))
                continue
            last_pred = time.time()
            if not self._ensure_model():
                continue
            if self._camera_uuid.get(stream) is None:
                continue
            tracks = self._latest_tracks(stream, redis_client)
            if tracks is None:
                continue
            boxes, metas = tracks
            try:
                triplets = self._model.predict(frame, boxes, topk=self.settings.topk) or []
            except Exception:
                log.exception("relate predict fallo")
                self._stop.wait(2)
                continue
            self.stats["predictions"] = self.stats.get("predictions", 0) + 1
            if triplets:
                try:
                    tops = []
                    for t in triplets[:4]:
                        si = int(getattr(t, "subject_idx", -1))
                        oi = int(getattr(t, "object_idx", -1))
                        sc = metas[si]["class"] if 0 <= si < len(metas) else "?"
                        oc = metas[oi]["class"] if 0 <= oi < len(metas) else "?"
                        sc_v = round(float(getattr(t, "score", 0) or 0), 2)
                        tops.append(f"{sc}-{getattr(t, 'predicate', '?')}-{oc}:{sc_v}")
                    log.info("relaciones: %s", tops)
                except Exception:
                    log.exception("log de relaciones fallo")
            now = time.time()
            frame_jpeg: bytes | None = None
            for t in triplets:
                try:
                    score = float(getattr(t, "score", 0) or 0)
                    if score < self.settings.score_threshold:
                        continue
                    si = int(getattr(t, "subject_idx", -1))
                    oi = int(getattr(t, "object_idx", -1))
                    predicate = str(getattr(t, "predicate", "") or "").strip()
                    if si < 0 or oi < 0 or si >= len(metas) or oi >= len(metas) or not predicate:
                        continue
                    sub, obj = metas[si], metas[oi]
                    if "road_sign" in (sub["class"], obj["class"]):
                        continue
                except Exception:
                    log.exception("procesamiento de tripleta fallo")
                    continue
                streak_key = (stream, predicate, sub["id"], obj["id"])
                self._streak[streak_key] = self._streak.get(streak_key, 0) + 1
                if self._streak[streak_key] < self.settings.min_frames:
                    continue
                cd_key = (stream, predicate, sub["id"], obj["id"])
                if now - self._last_relates.get(cd_key, 0.0) < self.settings.cooldown_s:
                    continue
                self._last_relates[cd_key] = now
                self._streak[streak_key] = 0
                if frame_jpeg is None:
                    ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    frame_jpeg = buf.tobytes() if ok2 else None
                self._emit(stream, sub, predicate, obj, score, frame_jpeg, now)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok" if self._model is not None else "loading",
            "model_error": self._model_error,
            "model": self.settings.model_id,
            "device": self.settings.device,
            "enabled": self._enabled,
            "cameras": [
                {
                    "stream": s,
                    "frames": self.stats.get("frames", 0),
                    "predictions": self.stats.get("predictions", 0),
                    "events": self.stats.get("events", 0),
                }
                for s in self.settings.cameras
            ],
            "vocabulary": self._vocab or list(DEFAULT_VOCABULARY),
        }
