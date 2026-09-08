from __future__ import annotations

import base64
import difflib
import hashlib
import json
import logging
import os
import queue
import re
import statistics
import threading
import time
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar

import cv2
import httpx
import numpy as np
import onnxruntime as ort
from fast_alpr import ALPR

from .config import Settings, StreamSpec

log = logging.getLogger(__name__)
_PLATE_CHARS = re.compile(r"[^A-Z0-9]")


def normalize_plate(value: str) -> str:
    return _PLATE_CHARS.sub("", value.upper())


def ocr_confidence(value: float | list[float] | None) -> float:
    if isinstance(value, list):
        return float(statistics.mean(value)) if value else 0.0
    return float(value or 0.0)


@dataclass(slots=True)
class CameraState:
    spec: StreamSpec
    status: str = "connecting"
    error: str | None = None
    last_frame_at: float | None = None
    frame_seq: int = 0
    inference_count: int = 0
    dropped_frames: int = 0
    inference_ms: float | None = None
    detections: list[dict[str, Any]] = field(default_factory=list)
    jpeg: bytes | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def describe(self, now: float, stale_after_s: float) -> dict[str, Any]:
        with self.lock:
            age = None if self.last_frame_at is None else max(0.0, now - self.last_frame_at)
            status = self.status
            if status == "live" and age is not None and age > stale_after_s:
                status = "stale"
            return {
                "camera_id": self.spec.camera_id,
                "source": self.spec.source,
                "status": status,
                "error": self.error,
                "last_frame_at": self.last_frame_at,
                "last_frame_age_s": None if age is None else round(age, 2),
                "frame_seq": self.frame_seq,
                "inference_count": self.inference_count,
                "dropped_frames": self.dropped_frames,
                "inference_ms": self.inference_ms,
                "detections": list(self.detections),
            }


FrameItem = tuple[StreamSpec, float, np.ndarray]


class BestShotTracker:
    """Agrupa las lecturas de un mismo vehículo mientras se aproxima y
    emite una sola: la de mayor certeza OCR (auto más cerca/nítido)."""

    def __init__(
        self,
        wait_s: float,
        emit_conf: float,
        emit: Callable[[str, float, dict[str, Any], bytes], None],
    ) -> None:
        self._wait_s = wait_s
        self._emit_conf = emit_conf
        self._emit = emit
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _similar(a: dict[str, Any], b: dict[str, Any]) -> bool:
        if a.get("box") and b.get("box"):
            ax1, ay1, ax2, ay2 = a["box"]
            bx1, by1, bx2, by2 = b["box"]
            ix = max(0, min(ax2, bx2) - max(ax1, bx1))
            iy = max(0, min(ay2, by2) - max(ay1, by1))
            inter = ix * iy
            area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
            area_b = max(1, (bx2 - bx1) * (by2 - by1))
            if inter / min(area_a, area_b) > 0.2:
                return True
        ratio = difflib.SequenceMatcher(None, a.get("plate", ""), b.get("plate", "")).ratio()
        return ratio >= 0.6

    def update(
        self, camera_id: str, detections: list[dict[str, Any]], jpeg: bytes, ts: float
    ) -> None:
        with self._lock:
            pending = self._pending.get(camera_id)
            if pending is not None and ts - pending["last_ts"] > self._wait_s:
                self._flush(camera_id)
                pending = None
            valid = [d for d in detections if 5 <= len(d.get("plate", "")) <= 8]
            valid.sort(key=lambda d: d["ocr_confidence"], reverse=True)
            for det in valid:
                if pending is None:
                    self._pending[camera_id] = {
                        "det": det,
                        "jpeg": jpeg,
                        "ts": ts,
                        "last_ts": ts,
                    }
                    pending = self._pending[camera_id]
                elif self._similar(pending["det"], det):
                    pending["last_ts"] = ts
                    if det["ocr_confidence"] > pending["det"]["ocr_confidence"]:
                        pending.update({"det": det, "jpeg": jpeg, "ts": ts})
                    if pending["det"]["ocr_confidence"] >= self._emit_conf:
                        self._flush(camera_id)
                        pending = None
                        break
                else:
                    self._flush(camera_id)
                    self._pending[camera_id] = {
                        "det": det,
                        "jpeg": jpeg,
                        "ts": ts,
                        "last_ts": ts,
                    }
                    pending = self._pending[camera_id]
                    break

    def _flush(self, camera_id: str) -> None:
        best = self._pending.pop(camera_id, None)
        if best is not None:
            self._emit(camera_id, best["ts"], best["det"], best["jpeg"])

    def flush_all(self) -> None:
        with self._lock:
            for camera_id in list(self._pending):
                self._flush(camera_id)


class ALPRRuntime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.states = {spec.camera_id: CameraState(spec) for spec in settings.streams}
        self._frames: queue.Queue[FrameItem] = queue.Queue(maxsize=max(4, len(self.states) * 2))
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self._events_lock = threading.Lock()
        self._last_event: dict[tuple[str, str], float] = {}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._alpr: ALPR | None = None
        self._event_client: httpx.Client | None = None
        self._vehicle_client: httpx.Client | None = None
        self._soap_client: httpx.Client | None = None
        self._vehicle_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
        self._vehicle_cache_lock = threading.Lock()
        self._emit_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=16)
        self._lookup_stats: dict[str, int] = {"attempts": 0, "ok": 0, "empty": 0, "timeout": 0}
        self._capture_events: dict[str, threading.Event] = {}
        self._capture_threads: dict[str, threading.Thread] = {}
        self._api_added: set[str] = set()
        self._tracker = BestShotTracker(
            settings.bestshot_wait_s, settings.bestshot_conf, self._maybe_emit_event
        )
        self.model_ready = False
        self.model_error: str | None = None
        self._ar_client: httpx.Client | None = None
        self.available_providers = ort.get_available_providers()

    def start(self) -> None:
        providers: list[str] | None = None
        if self.settings.device == "cuda":
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        try:
            self._alpr = ALPR(
                detector_model=self.settings.detector_model,
                detector_conf_thresh=self.settings.detector_confidence,
                detector_providers=providers,
                ocr_model=self.settings.ocr_model,
                ocr_device=self.settings.device,
                ocr_providers=providers,
            )
            self.model_ready = True
        except Exception as exc:
            self.model_error = str(exc)
            log.exception("failed to initialize FastALPR")
            raise

        self._event_client = httpx.Client(timeout=10)
        if self.settings.vehicle_provider == "autoriesgo":
            if self.settings.autoriesgo_key:
                self._ar_client = httpx.Client(
                    timeout=20,
                    headers={"X-Api-Key": self.settings.autoriesgo_key},
                )
                log.info("vehicle lookup enabled via AutoRiesgo (keyed API)")
            else:
                log.warning("vehicle_provider=autoriesgo sin API key; lookup desactivado")
        if self.settings.vehicle_provider == "demo":
            log.info("vehicle lookup enabled in DEMO mode (datos sintéticos locales)")
        elif self.settings.vehicle_provider == "matriculaapi":
            if self.settings.matricula_username and self.settings.matricula_key:
                # Las consultas en frío a SRCEI pueden tardar >20 s.
                self._soap_client = httpx.Client(timeout=30)
                log.info(
                    "vehicle lookup enabled via matriculaapi (%s) — solo se envía la patente; "
                    "cámaras: %s",
                    self.settings.matricula_endpoint,
                    self.settings.vehicle_cameras or "todas",
                )
            else:
                log.warning(
                    "vehicle_provider=matriculaapi sin credenciales; lookup desactivado"
                )
        elif self.settings.vehicle_api_key:
            self._vehicle_client = httpx.Client(
                timeout=3,
                headers={
                    "X-API-KEY": self.settings.vehicle_api_key,
                    "accept": "application/json",
                },
            )
            log.info("vehicle lookup enabled via %s", self.settings.vehicle_api_url)
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        inference = threading.Thread(target=self._inference_loop, name="alpr-inference", daemon=True)
        self._threads.append(inference)
        inference.start()
        emitter = threading.Thread(target=self._emit_worker, name="alpr-emit", daemon=True)
        self._threads.append(emitter)
        emitter.start()
        for spec in self.settings.streams:
            self._start_capture(spec)
        if self.settings.ingest_token:
            reconciler = threading.Thread(
                target=self._reconcile_loop, name="alpr-reconcile", daemon=True
            )
            self._threads.append(reconciler)
            reconciler.start()
            log.info(
                "camera reconciliation enabled (%ds) against %s",
                self.settings.reconcile_seconds,
                self.settings.api_url,
            )
        log.info("FastALPR started for %d cameras", len(self.states))

    def _start_capture(self, spec: StreamSpec) -> None:
        if spec.camera_id in self._capture_threads:
            return
        self.states[spec.camera_id] = CameraState(spec)
        stop_event = threading.Event()
        self._capture_events[spec.camera_id] = stop_event
        thread = threading.Thread(
            target=self._capture_loop,
            args=(spec, stop_event),
            name=f"alpr-capture-{spec.camera_id}",
            daemon=True,
        )
        self._capture_threads[spec.camera_id] = thread
        thread.start()

    def _stop_capture(self, camera_id: str) -> None:
        event = self._capture_events.pop(camera_id, None)
        if event is not None:
            event.set()
        self._capture_threads.pop(camera_id, None)
        self.states.pop(camera_id, None)
        stale = [key for key in self._last_event if key[0] == camera_id]
        for key in stale:
            self._last_event.pop(key, None)

    def _reconcile_loop(self) -> None:
        client = httpx.Client(
            timeout=10,
            headers={"Authorization": f"Bearer {self.settings.ingest_token}"},
        )
        while not self._stop.is_set():
            try:
                response = client.get(f"{self.settings.api_url}/cameras/active")
                response.raise_for_status()
                payloads = response.json()
                if isinstance(payloads, list):
                    self._reconcile_cameras(payloads)
            except (httpx.HTTPError, ValueError, TypeError):
                log.warning("camera reconciliation failed; keeping current set")
            try:
                cfg_response = client.get(f"{self.settings.api_url}/alpr-config")
                cfg_response.raise_for_status()
                self._apply_dynamic_config(cfg_response.json())
            except (httpx.HTTPError, ValueError, TypeError):
                pass
            self._stop.wait(self.settings.reconcile_seconds)
        client.close()

    def _reconcile_cameras(self, payloads: list[dict[str, Any]]) -> None:
        desired: dict[str, dict[str, Any]] = {}
        for payload in payloads:
            stream_id = str(payload.get("stream_id") or "")
            if stream_id and str(payload.get("analytics_profile") or "traffic") == "matriculas":
                desired[stream_id] = payload
        for camera_id in list(self.states):
            if camera_id not in desired:
                log.info("removing ALPR camera %s (not matriculas or deleted)", camera_id)
                self._stop_capture(camera_id)
                self._api_added.discard(camera_id)
        for stream_id, payload in desired.items():
            if stream_id in self.states:
                continue
            spec = self._spec_from_payload(payload)
            if spec is None:
                continue
            log.info("adding ALPR camera %s (source=%s)", spec.camera_id, spec.source)
            self._api_added.add(stream_id)
            self._start_capture(spec)

    @staticmethod
    def _spec_from_payload(payload: dict[str, Any]) -> StreamSpec | None:
        stream_id = str(payload.get("stream_id") or "")
        if not stream_id:
            return None
        rtsp = str(payload.get("rtsp_url") or "").strip()
        prefix = "rtsp://go2rtc:8554/"
        source = rtsp.removeprefix(prefix)
        crop = None
        roi = payload.get("roi_config")
        if isinstance(roi, dict):
            zone = roi.get("alpr_zone")
            if isinstance(zone, dict):
                try:
                    x1, y1, x2, y2 = (int(zone[k]) for k in ("x1", "y1", "x2", "y2"))
                    if x2 - x1 >= 40 and y2 - y1 >= 40:
                        crop = (x1, y1, x2, y2)
                except (KeyError, TypeError, ValueError):
                    crop = None
        return StreamSpec(camera_id=stream_id, source=source or stream_id, crop=crop)

    def stop(self) -> None:
        self._stop.set()
        self._tracker.flush_all()
        for event in self._capture_events.values():
            event.set()
        for thread in self._capture_threads.values():
            thread.join(timeout=3)
        for thread in self._threads:
            thread.join(timeout=3)
        if self._event_client is not None:
            self._event_client.close()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def cameras(self) -> list[dict[str, Any]]:
        now = time.time()
        return [state.describe(now, self.settings.stale_after_s) for state in self.states.values()]

    def recent_events(self) -> list[dict[str, Any]]:
        with self._events_lock:
            return list(reversed(self._events))

    def latest_jpeg(self, camera_id: str) -> tuple[int, bytes | None]:
        state = self.states[camera_id]
        with state.lock:
            return state.frame_seq, state.jpeg

    def health(self) -> dict[str, Any]:
        cameras = self.cameras()
        live = sum(camera["status"] == "live" for camera in cameras)
        status = "healthy" if self.model_ready and live == len(cameras) else "degraded"
        if not self.model_ready:
            status = "starting" if self.model_error is None else "unhealthy"
        return {
            "status": status,
            "ready": self.model_ready,
            "vehicle_lookups": dict(self._lookup_stats),
            "model": {
                "detector": self.settings.detector_model,
                "ocr": self.settings.ocr_model,
                "device": self.settings.device,
                "providers": self.available_providers,
                "error": self.model_error,
            },
            "active_cameras": len(cameras),
            "live_cameras": live,
            "queue_depth": self._frames.qsize(),
            "cameras": cameras,
        }

    def _capture_loop(self, spec: StreamSpec, stop_event: threading.Event) -> None:
        state = self.states[spec.camera_id]
        interval = 1.0 / self.settings.target_fps
        uri = (
            spec.source
            if spec.source.startswith("rtsp://")
            else f"{self.settings.rtsp_base.rstrip('/')}/{spec.source}"
        )
        while not stop_event.is_set():
            started = time.monotonic()
            try:
                # go2rtc's frame.jpeg costs ~2s per request (<=0.5 fps real).
                # Its RTSP remux sustains ~30 fps; frames are decoded
                # continuously and only sampled at the target rate.
                cap = cv2.VideoCapture(uri, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    raise ValueError("cannot open RTSP source")
                last_push = 0.0
                while not stop_event.is_set():
                    if not cap.grab():
                        raise ValueError("RTSP stream ended")
                    now = time.monotonic()
                    if now - last_push < interval:
                        continue
                    ok, frame = cap.retrieve()
                    if not ok or frame is None:
                        continue
                    last_push = now
                    captured_at = time.time()
                    try:
                        self._frames.put_nowait((spec, captured_at, frame))
                    except queue.Full:
                        with state.lock:
                            state.dropped_frames += 1
                    with state.lock:
                        state.error = None
                        if state.status != "live":
                            state.status = "waiting-inference"
                cap.release()
            except (cv2.error, ValueError) as exc:
                with state.lock:
                    frame_age = (
                        None
                        if state.last_frame_at is None
                        else time.time() - state.last_frame_at
                    )
                    if frame_age is None or frame_age > self.settings.stale_after_s:
                        state.status = "offline"
                    state.error = str(exc)[:240]
                log.warning("RTSP capture failed for %s: %s", spec.camera_id, exc)
                stop_event.wait(max(2.0, interval - (time.monotonic() - started)))

    @staticmethod
    def _work_frame(
        frame: np.ndarray, crop: tuple[int, int, int, int] | None
    ) -> tuple[np.ndarray, float, float]:
        if crop is None:
            return frame, 0.0, 0.0
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = crop
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 - x1 < 40 or y2 - y1 < 40:
            return frame, 0.0, 0.0
        return frame[y1:y2, x1:x2], float(x1), float(y1)

    def _inference_loop(self) -> None:
        assert self._alpr is not None
        while not self._stop.is_set():
            try:
                spec, captured_at, frame = self._frames.get(timeout=0.5)
            except queue.Empty:
                continue
            state = self.states.get(spec.camera_id)
            if state is None:
                continue
            started = time.perf_counter()
            try:
                work, ox, oy = self._work_frame(frame, spec.crop)
                results = self._alpr.predict(work)
                detections = self._serialize_results(results)
                if ox or oy:
                    for det in detections:
                        b = det["box"]
                        det["box"] = [
                            int(b[0] + ox),
                            int(b[1] + oy),
                            int(b[2] + ox),
                            int(b[3] + oy),
                        ]
                annotated = self._draw(frame, spec.camera_id, detections, spec.crop)
                encoded, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not encoded:
                    raise ValueError("failed to encode annotated frame")
                jpeg_bytes = jpeg.tobytes()
                inference_ms = round((time.perf_counter() - started) * 1000, 1)
                with state.lock:
                    state.status = "live"
                    state.error = None
                    state.last_frame_at = captured_at
                    state.frame_seq += 1
                    state.inference_count += 1
                    state.inference_ms = inference_ms
                    state.detections = detections
                    state.jpeg = jpeg_bytes
                if detections:
                    for det in detections:
                        log.info(
                            "lectura cruda cam=%s plate=%r det=%.2f ocr=%.2f",
                            spec.camera_id,
                            det.get("plate"),
                            det.get("detector_confidence", 0),
                            det.get("ocr_confidence", 0),
                        )
                self._tracker.update(spec.camera_id, detections, jpeg_bytes, captured_at)
            except Exception as exc:
                with state.lock:
                    state.status = "error"
                    state.error = str(exc)[:240]
                log.exception("ALPR inference failed for %s", spec.camera_id)

    @staticmethod
    def _serialize_results(results: list[Any]) -> list[dict[str, Any]]:
        detections: list[dict[str, Any]] = []
        for result in results:
            box = result.detection.bounding_box
            ocr = result.ocr
            raw_text = ocr.text if ocr is not None else ""
            detections.append(
                {
                    "plate": normalize_plate(raw_text),
                    "raw_text": raw_text,
                    "detector_confidence": round(float(result.detection.confidence), 4),
                    "ocr_confidence": round(
                        ocr_confidence(ocr.confidence if ocr is not None else None), 4
                    ),
                    "region": ocr.region if ocr is not None else None,
                    "box": [int(box.x1), int(box.y1), int(box.x2), int(box.y2)],
                }
            )
        return detections

    @staticmethod
    def _draw(
        frame: np.ndarray,
        camera_id: str,
        detections: list[dict[str, Any]],
        crop: tuple[int, int, int, int] | None = None,
    ) -> np.ndarray:
        image = frame.copy()
        if crop is not None:
            x1, y1, x2, y2 = crop
            cv2.rectangle(image, (x1, y1), (x2, y2), (255, 170, 60), 2)
            cv2.putText(
                image,
                "zona ALPR",
                (x1 + 6, y1 + 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 170, 60),
                2,
                cv2.LINE_AA,
            )
        for detection in detections:
            x1, y1, x2, y2 = detection["box"]
            plate = detection["plate"] or "PLATE"
            label = f"{plate} {detection['ocr_confidence'] * 100:.0f}%"
            cv2.rectangle(image, (x1, y1), (x2, y2), (39, 224, 170), 3)
            cv2.putText(
                image,
                label,
                (max(4, x1), max(24, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (39, 224, 170),
                2,
                cv2.LINE_AA,
            )
        cv2.rectangle(image, (0, 0), (min(image.shape[1], 360), 38), (8, 15, 26), -1)
        cv2.putText(
            image,
            f"{camera_id}  ALPR {len(detections)}",
            (12, 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (240, 244, 248),
            2,
            cv2.LINE_AA,
        )
        return image

    def _maybe_emit_event(
        self,
        camera_id: str,
        timestamp: float,
        detection: dict[str, Any],
        jpeg: bytes,
    ) -> None:
        plate = detection["plate"]
        log.info(
            "emit intento cam=%s plate=%r len=%d ocr=%.4f det=%.4f ocr_min=%.2f cooldown_ago=%.1f",
            camera_id, plate, len(plate), detection["ocr_confidence"], detection["detector_confidence"],
            self.settings.ocr_confidence,
            timestamp - self._last_event.get((camera_id, plate), 0.0),
        )
        if not 5 <= len(plate) <= 8:
            return
        if detection["ocr_confidence"] < self.settings.ocr_confidence:
            return
        key = (camera_id, plate)
        if timestamp - self._last_event.get(key, 0.0) < self.settings.event_cooldown_s:
            return
        self._last_event[key] = timestamp
        metadata = {
            "plate_text": plate,
            "detector_confidence": detection["detector_confidence"],
            "ocr_confidence": detection["ocr_confidence"],
            "region": detection["region"],
            "box": detection["box"],
            "backend": "fast-alpr",
        }
        # El filtro real es el perfil "matriculas" de cada cámara (reconciler);
        # todas las cámaras ALPR consultan vehículo.
        allowed: set[str] = set()
        provider = self.settings.vehicle_provider
        gate = self.settings.validate_plate and provider in ("boostr", "matriculaapi", "autoriesgo")
        # Consultar solo cuando YOLO y OCR dan el máximo: ahorra créditos.
        certain = (
            detection["ocr_confidence"] >= self.settings.query_ocr_conf
            and detection["detector_confidence"] >= self.settings.query_det_conf
        )
        vehicle = None
        if (not allowed or camera_id in allowed) and certain:
            vehicle = self._vehicle_data(plate)
        if vehicle:
            metadata["vehicle"] = vehicle
        elif gate:
            # Regla: solo entran a eventos las placas confirmadas por la
            # fuente oficial (Registro Civil) — el OCR solo no basta.
            log.info("lectura %s no validada por Registro Civil; evento descartado", plate)
            return
        if self.settings.region:
            # El OCR global adivina la región por píxeles y suele errar; el
            # despliegue tiene una región conocida y esa manda.
            metadata["region"] = self.settings.region
        event = {
            "event_type": "ALPR",
            "camera_id": camera_id,
            "timestamp": timestamp,
            "confidence": min(
                detection["detector_confidence"], detection["ocr_confidence"]
            ),
            "priority": "info",
            "rule_id": "fast-alpr",
            "metadata": metadata,
            "snapshot_jpeg": base64.b64encode(jpeg).decode("ascii"),
        }
        with self._events_lock:
            self._events.append(
                {
                    **event,
                    "snapshot_jpeg": None,
                    "timestamp_iso": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
                }
            )
        try:
            self._emit_queue.put_nowait(event)
        except queue.Full:
            log.warning("emit queue full; dropping ALPR event for %s", camera_id)

    def _vehicle_data(self, plate: str) -> dict[str, Any] | None:
        provider = self.settings.vehicle_provider
        log.info("vehicle_data provider=%s plate=%s", provider, plate)
        if provider == "demo":
            data = self._demo_vehicle(plate)
            ttl = 7 * 86400 if data else 3600
            now = time.time()
            with self._vehicle_cache_lock:
                self._vehicle_cache[plate] = (now + ttl, data)
            return data
        if provider == "autoriesgo" and self._ar_client is not None:
            now = time.time()
            with self._vehicle_cache_lock:
                cached = self._vehicle_cache.get(plate)
                if cached and cached[0] > now:
                    return cached[1]
            self._lookup_stats["attempts"] += 1
            data = self._fetch_vehicle_autoriesgo(plate)
            self._lookup_stats["ok" if data else "empty"] += 1
            ttl = 7 * 86400 if data else 3600
            with self._vehicle_cache_lock:
                self._vehicle_cache[plate] = (now + ttl, data)
            return data
        if provider == "matriculaapi" and self._soap_client is not None:
            now = time.time()
            with self._vehicle_cache_lock:
                cached = self._vehicle_cache.get(plate)
                if cached and cached[0] > now:
                    return cached[1]
            self._lookup_stats["attempts"] += 1
            data, timed_out = self._fetch_vehicle_soap(plate)
            self._lookup_stats["ok" if data else ("timeout" if timed_out else "empty")] += 1
            # SRCEI indexa patentes nuevas de forma asíncrona (>60 s la
            # primera vez): reintenta pronto en vez de castigar por 1 h.
            ttl = 7 * 86400 if data else (300 if timed_out else 3600)
            with self._vehicle_cache_lock:
                self._vehicle_cache[plate] = (now + ttl, data)
            return data
        if self._vehicle_client is None:
            return None
        now = time.time()
        with self._vehicle_cache_lock:
            cached = self._vehicle_cache.get(plate)
            if cached and cached[0] > now:
                return cached[1]
        data = self._fetch_vehicle(plate)
        ttl = 7 * 86400 if data else 3600
        with self._vehicle_cache_lock:
            self._vehicle_cache[plate] = (now + ttl, data)
        return data

    def _fetch_vehicle_soap(self, plate: str) -> dict[str, Any] | None:
        assert self._soap_client is not None
        operation = self.settings.matricula_operation
        envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <{operation} xmlns="http://regcheck.org.uk">
      <username>{self.settings.matricula_username}</username>
      <LicenseKey>{self.settings.matricula_key}</LicenseKey>
      <RegistrationNumber>{plate}</RegistrationNumber>
    </{operation}>
  </soap:Body>
</soap:Envelope>"""
        try:
            response = self._soap_client.post(
                self.settings.matricula_endpoint,
                content=envelope.encode(),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": f"http://regcheck.org.uk/{operation}",
                },
            )
            response.raise_for_status()
            return (
                self._parse_soap_vehicle(
                    response.text, plate, self.settings.vehicle_include_owner
                ),
                False,
            )
        except httpx.TimeoutException:
            log.warning("matriculaapi lookup timed out for %s (SRCEI indexando)", plate)
            return None, True
        except (httpx.HTTPError, ValueError, SyntaxError):
            log.warning("matriculaapi lookup failed for %s", plate)
            return None, False

    def _fetch_vehicle_autoriesgo(self, plate: str) -> dict[str, Any] | None:
        assert self._ar_client is not None
        try:
            response = self._ar_client.get(
                f"{self.settings.autoriesgo_endpoint}/{plate}?include_owner=true"
            )
            if response.status_code == 429:
                log.warning("autoriesgo rate limit (5/min) para %s", plate)
                return None
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            log.warning("autoriesgo lookup failed for %s", plate)
            return None
        if not isinstance(payload, dict) or not payload.get("found"):
            return None
        raw = payload.get("vehicle") or {}

        def pick(*keys: str) -> Any:
            for key in keys:
                value = raw.get(key)
                if value not in (None, ""):
                    return value
            return None

        vehicle: dict[str, Any] = {
            "plate": plate,
            "provider": "autoriesgo",
            "make": pick("make"),
            "model": pick("model"),
            "version": pick("version"),
            "year": pick("year"),
            "type": pick("type"),
            "color": pick("color"),
            "fuel": pick("gas_type"),
            "engine": pick("engine"),
            "engine_size": pick("engine_size"),
            "transmission": pick("transmission"),
            "kilometers": pick("kilometers"),
            "dv": pick("dv"),
            "vin": pick("chassis"),
        }
        owner = raw.get("owner")
        if isinstance(owner, dict) and owner.get("fullname"):
            vehicle["owner"] = {
                "fullname": owner.get("fullname"),
                "documentNumber": owner.get("documentNumber"),
            }
        prt = raw.get("prt")
        if isinstance(prt, dict) and prt.get("status"):
            vehicle["prt"] = {
                "status": prt.get("status"),
                "date": prt.get("date"),
                "due_date": prt.get("due_date"),
            }
        return vehicle

    _DYNAMIC_CONFIG_MAP = {
        "provider": ("vehicle_provider", str),
        "cameras": ("vehicle_cameras", str),
        "username": ("matricula_username", str),
        "license_key": ("matricula_key", str),
        "endpoint": ("matricula_endpoint", str),
        "operation": ("matricula_operation", str),
        "query_det_conf": ("query_det_conf", float),
        "query_ocr_conf": ("query_ocr_conf", float),
        "validate_plate": ("validate_plate", bool),
        "include_owner": ("vehicle_include_owner", bool),
        "region": ("region", str),
        "api_url": ("vehicle_api_url", str),
        "api_key": ("vehicle_api_key", str),
        "ar_api_key": ("autoriesgo_key", str),
    }

    def _apply_dynamic_config(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        changed = False
        for key, (attr, cast) in self._DYNAMIC_CONFIG_MAP.items():
            value = payload.get(key)
            if value in (None, ""):
                continue
            try:
                casted = cast(value)
            except (TypeError, ValueError):
                continue
            if getattr(self.settings, attr, None) != casted:
                setattr(self.settings, attr, casted)
                changed = True
        if (
            self.settings.vehicle_provider == "autoriesgo"
            and self.settings.autoriesgo_key
        ):
            current = self._ar_client.headers.get("X-Api-Key") if self._ar_client else None
            if current != self.settings.autoriesgo_key:
                if self._ar_client is not None:
                    self._ar_client.close()
                self._ar_client = httpx.Client(
                    timeout=20,
                    headers={"X-Api-Key": self.settings.autoriesgo_key},
                )
                log.info("AutoRiesgo client (re)configurado dinámicamente")
        if changed:
            log.info(
                "config dinámica aplicada: provider=%s gate=%s det=%.2f ocr=%.2f",
                self.settings.vehicle_provider,
                self.settings.validate_plate,
                self.settings.query_det_conf,
                self.settings.query_ocr_conf,
            )

    @staticmethod
    def _parse_soap_vehicle(
        text: str, plate: str, include_owner: bool
    ) -> dict[str, Any] | None:
        root = ET.fromstring(text)
        raw_json = None
        for element in root.iter():
            if element.tag.lower().endswith("vehiclejson") and element.text:
                raw_json = element.text
                break
        if not raw_json:
            return None
        data = json.loads(raw_json)
        if not isinstance(data, dict):
            return None

        def pick(*keys: str) -> Any:
            for key in keys:
                value = data.get(key)
                if isinstance(value, dict):
                    inner = value.get("CurrentTextValue") or value.get("value")
                    if inner not in (None, ""):
                        return inner
                if value not in (None, ""):
                    return value
            return None

        vehicle: dict[str, Any] = {
            "plate": plate,
            "provider": "matriculaapi",
            "make": pick("CarMake", "make", "Make"),
            "model": pick("CarModel", "model", "Model"),
            "year": pick("RegistrationYear", "year", "Year"),
            "type": pick("VehicleType", "BodyStyle", "type"),
            "color": pick("Colour", "Color", "color"),
            "fuel": pick("Fuel", "FuelType", "fuelType"),
            "engine": pick("EngineCode", "EngineNumber", "engineNumber"),
            "vin": pick("VIN", "Chassis"),
        }
        if include_owner:
            owner = pick("Owner", "owner", "Propietario", "propietario")
            if isinstance(owner, dict) and owner:
                vehicle["owner"] = {
                    "fullname": owner.get("Name") or owner.get("fullname") or "",
                    "documentNumber": owner.get("NationalId")
                    or owner.get("documentNumber")
                    or "",
                }
        vehicle = {k: v for k, v in vehicle.items() if v not in (None, "")}
        if len(vehicle) <= 2:
            return None
        return vehicle

    _DEMO_MAKES: ClassVar[dict[str, list[str]]] = {
        "CHEVROLET": ["AVEO", "SAIL", "CORSA", "SPARK"],
        "PEUGEOT": ["407", "208", "301", "PARTNER"],
        "TOYOTA": ["YARIS", "HILUX", "COROLLA", "RAV4"],
        "HYUNDAI": ["ACCENT", "TUCSON", "I10", "SANTA FE"],
        "NISSAN": ["NP300", "SENTRA", "X-TRAIL", "MARCH"],
        "KIA": ["RIO", "SPORTAGE", "MORNING", "SELTOS"],
        "SUZUKI": ["SWIFT", "DZIRE", "VITARA", "ERTIGA"],
        "MAZDA": ["3", "CX-5", "BT-50", "2"],
    }
    _DEMO_TYPES: ClassVar[list[str]] = [
        "AUTOMOVIL",
        "AUTOMOVIL",
        "CAMIONETA",
        "SUV",
        "AUTOMOVIL",
    ]

    def _demo_vehicle(self, plate: str) -> dict[str, Any]:
        """Datos deterministas por patente para probar el flujo sin API pagada."""
        seed = int(hashlib.sha256(plate.encode()).hexdigest()[:8], 16)
        make = list(self._DEMO_MAKES)[seed % len(self._DEMO_MAKES)]
        models = self._DEMO_MAKES[make]
        model = models[(seed // 7) % len(models)]
        year = 2008 + (seed // 13) % 17
        vtype = self._DEMO_TYPES[(seed // 11) % len(self._DEMO_TYPES)]
        engine = f"D{seed % 100000:05d}"
        vehicle: dict[str, Any] = {
            "plate": plate,
            "make": make,
            "model": model,
            "year": year,
            "type": vtype,
            "engine": engine,
            "provider": "demo",
        }
        if self.settings.vehicle_include_owner:
            vehicle["owner"] = {"fullname": "TITULAR DEMO", "documentNumber": "12.345.678-9"}
        return vehicle

    def _fetch_vehicle(self, plate: str) -> dict[str, Any] | None:
        assert self._vehicle_client is not None
        try:
            response = self._vehicle_client.get(
                self.settings.vehicle_api_url.format(plate=plate)
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            log.warning("vehicle lookup failed for %s", plate)
            return None
        if not isinstance(payload, dict) or payload.get("status") != "success":
            log.info("vehicle lookup empty for %s: %s", plate, payload.get("code"))
            return None
        raw = payload.get("data") or {}
        if not isinstance(raw, dict):
            return None
        vehicle: dict[str, Any] = {
            key: raw[key]
            for key in ("plate", "dv", "make", "model", "year", "type", "engine")
            if raw.get(key) not in (None, "")
        }
        if self.settings.vehicle_include_owner and isinstance(raw.get("owner"), dict):
            vehicle["owner"] = raw["owner"]
        return vehicle or None

    def _emit_worker(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._emit_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if not self.settings.ingest_token or self._event_client is None:
                continue
            try:
                response = self._event_client.post(
                    f"{self.settings.api_url}/events",
                    headers={"Authorization": f"Bearer {self.settings.ingest_token}"},
                    json=event,
                )
                response.raise_for_status()
            except Exception:
                log.exception("failed to send ALPR event for %s", event.get("camera_id"))
