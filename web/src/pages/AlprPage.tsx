import { Activity, CameraOff, Maximize2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, auth, type AlprCamera, type EventItem } from "../lib/api";
import { fmtDateTime } from "../lib/format";

const REFRESH_MS = 1000;
const SNAPSHOT_REFRESH_MS = 15000;
const NAMES_REFRESH_MS = 30000;
// Los navegadores limitan ~6 conexiones por host:puerto; dejamos margen.
const MAX_STREAMS = 4;

// Puerto dedicado para MJPEG: los navegadores limitan ~6 conexiones por
// host:puerto y el grid necesita un pool propio.
const STREAM_PORT = 8092;

function streamBase(): string {
  if (location.protocol !== "http:") return "";
  return `${location.protocol}//${location.hostname}:${STREAM_PORT}`;
}

const STATUS_LABEL: Record<string, string> = {
  live: "en vivo",
  "waiting-inference": "procesando",
  stale: "sin frames",
  connecting: "conectando",
};

function statusStyle(status: string): string {
  if (status === "live") return "text-info border-info/40 bg-info/15";
  if (status === "waiting-inference" || status === "stale")
    return "text-warn border-warn/40 bg-warn/15";
  if (status === "connecting") return "text-white/70 border-white/20 bg-black/40";
  return "text-crit border-crit/40 bg-crit/15";
}

function LiveDot() {
  return (
    <span className="relative flex h-2 w-2">
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-info opacity-60" />
      <span className="relative inline-flex h-2 w-2 rounded-full bg-info" />
    </span>
  );
}

function SnapshotFrame({ cameraId }: { cameraId: string }) {
  const [ts, setTs] = useState(() => Date.now());
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const timer = setInterval(() => {
      setFailed(false);
      setTs(Date.now());
    }, SNAPSHOT_REFRESH_MS);
    return () => clearInterval(timer);
  }, []);
  if (failed) {
    return (
      <div className="flex h-full items-center justify-center bg-black font-mono text-xs text-dim">
        sin señal
      </div>
    );
  }
  return (
    <img
      src={`${streamBase()}/alpr/cameras/${encodeURIComponent(cameraId)}/snapshot.jpg?t=${ts}`}
      alt={cameraId}
      onError={() => setFailed(true)}
      className="h-full w-full bg-black object-cover opacity-90"
    />
  );
}

function StreamFrame({
  camera,
  active,
  onInView,
}: {
  camera: AlprCamera;
  active: boolean;
  onInView: (cameraId: string, inView: boolean) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  // Fuentes públicas (Caltrans/YouTube) se cortan a ratos: reintenta solo.
  useEffect(() => {
    if (!failed) return;
    const timer = setTimeout(() => {
      setFailed(false);
      setAttempt((a) => a + 1);
    }, 6000);
    return () => clearTimeout(timer);
  }, [failed]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      (entries) => onInView(camera.camera_id, entries.some((e) => e.isIntersecting)),
      { rootMargin: "120px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [camera.camera_id, onInView]);

  return (
    <div ref={ref} className="absolute inset-0">
      {!active ? (
        <SnapshotFrame cameraId={camera.camera_id} />
      ) : failed ? (
        <div className="flex h-full flex-col items-center justify-center gap-1 bg-black font-mono text-xs text-dim">
          <span>reconectando…</span>
          <span className="text-[10px] opacity-70">{camera.camera_id}</span>
        </div>
      ) : (
        <img
          key={attempt}
          src={`${streamBase()}/alpr/cameras/${encodeURIComponent(camera.camera_id)}/stream.mjpg?r=${attempt}`}
          alt={camera.camera_id}
          onError={() => setFailed(true)}
          className="h-full w-full bg-black object-contain"
        />
      )}
    </div>
  );
}

function CameraCard({
  camera,
  name,
  active,
  onInView,
  onMaximize,
}: {
  camera: AlprCamera;
  name: string;
  active: boolean;
  onInView: (cameraId: string, inView: boolean) => void;
  onMaximize: (cameraId: string) => void;
}) {
  return (
    <article
      onClick={() => onMaximize(camera.camera_id)}
      className="group cursor-pointer overflow-hidden rounded-xl border border-line bg-panel shadow-lg shadow-black/30 transition duration-200 hover:border-info/40 hover:shadow-info/10"
    >
      <div className="relative aspect-video w-full bg-black">
        <StreamFrame camera={camera} active={active} onInView={onInView} />
        <div className="pointer-events-none absolute inset-0 flex items-start justify-end p-2 opacity-0 transition group-hover:opacity-100">
          <span className="rounded-md border border-white/20 bg-black/60 p-1.5 text-white/90 backdrop-blur-sm">
            <Maximize2 size={13} />
          </span>
        </div>
        <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-2 bg-gradient-to-b from-black/75 via-black/30 to-transparent p-2.5">
          <div className="flex min-w-0 items-center gap-2">
            {camera.status === "live" && <LiveDot />}
            <span className="truncate font-mono text-[11px] font-semibold tracking-wide text-white/90">
              {name}
            </span>
          </div>
          <span
            className={`shrink-0 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider backdrop-blur-sm ${statusStyle(camera.status)}`}
          >
            {STATUS_LABEL[camera.status] ?? camera.status}
          </span>
        </div>
        {camera.detections.length > 0 && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-wrap gap-1.5 bg-gradient-to-t from-black/85 via-black/40 to-transparent p-2.5">
            {camera.detections.map((d, i) => (
              <span
                key={i}
                className="rounded-md border border-info/30 bg-black/60 px-2 py-0.5 font-mono text-[11px] font-semibold tracking-[0.18em] text-info backdrop-blur-sm"
              >
                {d.plate || "·····"}
                <span className="ml-1.5 font-normal tracking-normal text-white/50">
                  {Math.round(d.ocr_confidence * 100)}%
                </span>
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="flex items-center justify-between px-3 py-2 font-mono text-[11px] text-mut">
        <span>
          {camera.inference_ms ?? "—"} ms · {camera.inference_count} frames
        </span>
        {camera.dropped_frames > 0 ? (
          <span className="text-warn">{camera.dropped_frames} descartados</span>
        ) : (
          <span className={active ? "text-info" : "text-dim"}>
            {active ? "video en vivo" : "preview 15 s"}
          </span>
        )}
      </div>
    </article>
  );
}

interface VehicleInfo {
  plate?: string;
  dv?: string;
  make?: string;
  model?: string;
  year?: number;
  type?: string;
  engine?: string;
  provider?: string;
  owner?: { fullname?: string; documentNumber?: string };
}

function VehicleBox({ vehicle }: { vehicle: VehicleInfo }) {
  const title = [vehicle.make, vehicle.model].filter(Boolean).join(" ");
  return (
    <div className="mt-3 rounded-lg border border-info/30 bg-info/5 p-3">
      <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-wider text-info">
        <span>Vehículo · Registro Civil</span>
        {vehicle.provider === "demo" && (
          <span className="rounded bg-amber-300/10 px-1.5 py-0.5 text-amber-300">
            datos demo
          </span>
        )}
      </div>
      <div className="mt-1 text-sm font-semibold text-ink">
        {title || "—"}
        {vehicle.year ? <span className="ml-1.5 font-normal text-mut">{vehicle.year}</span> : null}
      </div>
      <div className="mt-0.5 font-mono text-[11px] text-mut">
        {[vehicle.type, vehicle.engine ? `motor ${vehicle.engine}` : "", vehicle.dv ? `dv ${vehicle.dv}` : ""]
          .filter(Boolean)
          .join(" · ")}
      </div>
      {vehicle.owner?.fullname && (
        <div className="mt-1 font-mono text-[11px] text-mut">
          propietario: {vehicle.owner.fullname}
          {vehicle.owner.documentNumber ? ` · ${vehicle.owner.documentNumber}` : ""}
        </div>
      )}
    </div>
  );
}

function ReadingDetail({
  reading,
  name,
  onClose,
  onAck,
  onFeedback,
}: {
  reading: EventItem;
  name: string;
  onClose: () => void;
  onAck: (id: string) => void;
  onFeedback: (id: string, value: "correct" | "false_positive") => void;
}) {
  const plate = String(reading.metadata?.plate_text ?? "—");
  const ocr = Number(reading.metadata?.ocr_confidence ?? 0);
  const region = reading.metadata?.region;
  const [zoom, setZoom] = useState(false);
  const [feedback, setFeedback] = useState<"correct" | "false_positive" | null>(null);

  useEffect(() => {
    if (!zoom) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setZoom(false);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [zoom]);

  const markFeedback = (value: "correct" | "false_positive") => {
    setFeedback(value);
    onFeedback(reading.event_id, value);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6"
      onClick={onClose}
    >
      <div
        className="max-h-full w-full max-w-2xl overflow-y-auto rounded-xl border border-line bg-panel p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <div className="font-mono text-2xl font-bold tracking-[0.2em]">{plate}</div>
            <div className="mt-1 text-xs text-mut">
              {name} · {fmtDateTime(reading.timestamp)}
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-line p-1.5 text-mut transition-colors hover:text-ink"
            aria-label="cerrar"
          >
            <X size={16} />
          </button>
        </div>
        {reading.snapshot_url ? (
          <img
            src={reading.snapshot_url}
            alt="evidencia"
            onClick={() => setZoom(true)}
            className="w-full cursor-zoom-in rounded-lg border border-line"
          />
        ) : (
          <div className="flex aspect-video w-full items-center justify-center rounded-lg border border-line bg-raised font-mono text-xs text-dim">
            sin evidencia
          </div>
        )}
        {zoom && reading.snapshot_url && (
          <div
            className="fixed inset-0 z-[60] flex cursor-zoom-out items-center justify-center bg-black/95 p-4"
            onClick={() => setZoom(false)}
          >
            <img
              src={reading.snapshot_url}
              alt="evidencia ampliada"
              className="max-h-full max-w-full object-contain"
            />
            <button
              onClick={() => setZoom(false)}
              className="absolute right-5 top-5 rounded-md border border-white/20 bg-black/60 p-2 text-white/80 hover:text-white"
              aria-label="cerrar zoom"
            >
              <X size={18} />
            </button>
          </div>
        )}
        {reading.metadata?.vehicle ? (
          <VehicleBox vehicle={reading.metadata.vehicle as VehicleInfo} />
        ) : null}
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-xs sm:grid-cols-3">
          <div>
            <dt className="text-dim">detector</dt>
            <dd className="text-ink">{(reading.confidence ?? 0).toFixed(3)}</dd>
          </div>
          <div>
            <dt className="text-dim">ocr</dt>
            <dd className="text-ink">{(ocr * 100).toFixed(1)}%</dd>
          </div>
          <div>
            <dt className="text-dim">región</dt>
            <dd className="text-ink">{String(region ?? "—")}</dd>
          </div>
          <div>
            <dt className="text-dim">cámara</dt>
            <dd className="truncate text-ink">{reading.camera_id}</dd>
          </div>
          <div>
            <dt className="text-dim">regla</dt>
            <dd className="truncate text-ink">{reading.rule_id}</dd>
          </div>
          <div>
            <dt className="text-dim">acuse</dt>
            <dd className="text-ink">
              {reading.acknowledged_at
                ? `${reading.acknowledged_by ?? ""} · ${fmtDateTime(reading.acknowledged_at)}`
                : "pendiente"}
            </dd>
          </div>
        </dl>
        <pre className="mt-3 max-h-40 overflow-auto rounded-lg border border-line/60 bg-black/30 p-3 font-mono text-[11px] leading-relaxed text-mut">
          {JSON.stringify(reading.metadata, null, 2)}
        </pre>
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line/60 pt-4">
          {!reading.acknowledged_at && (
            <button
              onClick={() => onAck(reading.event_id)}
              className="rounded-md border border-line px-3 py-1.5 text-xs text-mut transition-colors hover:border-info hover:text-info"
            >
              Acusar recibo
            </button>
          )}
          <span className="font-mono text-[10px] text-dim">¿lectura correcta?</span>
          <button
            onClick={() => markFeedback("correct")}
            className={`rounded border px-2.5 py-1 text-xs transition-colors ${
              feedback === "correct"
                ? "border-info bg-info/10 text-info"
                : "border-line text-mut hover:border-info hover:text-info"
            }`}
          >
            sí
          </button>
          <button
            onClick={() => markFeedback("false_positive")}
            className={`rounded border px-2.5 py-1 text-xs transition-colors ${
              feedback === "false_positive"
                ? "border-crit bg-crit/10 text-crit"
                : "border-line text-mut hover:border-crit hover:text-crit"
            }`}
          >
            falso positivo
          </button>
          {feedback && (
            <span className="font-mono text-[10px] text-info">✓ registrado</span>
          )}
        </div>
      </div>
    </div>
  );
}

function CameraModal({
  camera,
  name,
  onClose,
}: {
  camera: AlprCamera;
  name: string;
  onClose: () => void;
}) {
  const noop = useCallback(() => {}, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6"
      onClick={onClose}
    >
      <div
        className="w-full max-w-6xl overflow-hidden rounded-xl border border-line bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="relative aspect-video w-full bg-black">
          <StreamFrame camera={camera} active onInView={noop} />
          <div className="pointer-events-none absolute inset-x-0 top-0 flex items-start justify-between gap-2 bg-gradient-to-b from-black/75 via-black/30 to-transparent p-3">
            <div className="flex min-w-0 items-center gap-2">
              {camera.status === "live" && <LiveDot />}
              <span className="truncate font-mono text-sm font-semibold tracking-wide text-white/90">
                {name}
              </span>
            </div>
            <span
              className={`shrink-0 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider backdrop-blur-sm ${statusStyle(camera.status)}`}
            >
              {STATUS_LABEL[camera.status] ?? camera.status}
            </span>
          </div>
          {camera.detections.length > 0 && (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-wrap gap-1.5 bg-gradient-to-t from-black/85 via-black/40 to-transparent p-3">
              {camera.detections.map((d, i) => (
                <span
                  key={i}
                  className="rounded-md border border-info/30 bg-black/60 px-2 py-0.5 font-mono text-xs font-semibold tracking-[0.18em] text-info backdrop-blur-sm"
                >
                  {d.plate || "·····"}
                  <span className="ml-1.5 font-normal tracking-normal text-white/50">
                    {Math.round(d.ocr_confidence * 100)}%
                  </span>
                </span>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center justify-between px-4 py-2.5">
          <span className="font-mono text-[11px] text-mut">
            {camera.inference_ms ?? "—"} ms · frame {camera.frame_seq} ·{" "}
            {camera.inference_count} frames
          </span>
          <button
            onClick={onClose}
            className="flex items-center gap-1.5 rounded-md border border-line px-3 py-1 text-xs text-mut transition-colors hover:text-ink"
          >
            <X size={13} /> cerrar
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AlprPage() {
  const [cameras, setCameras] = useState<AlprCamera[]>([]);
  const [readings, setReadings] = useState<EventItem[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<EventItem | null>(null);
  const [maximized, setMaximized] = useState<string | null>(null);
  const [inViewIds, setInViewIds] = useState<Set<string>>(() => new Set());

  const handleInView = useCallback((cameraId: string, isIn: boolean) => {
    setInViewIds((prev) => {
      const next = new Set(prev);
      if (isIn) next.add(cameraId);
      else next.delete(cameraId);
      if (next.size === prev.size && [...next].every((id) => prev.has(id))) return prev;
      return next;
    });
  }, []);

  useEffect(() => {
    auth.ensureCookie();
    const loadNames = () =>
      api
        .cameras()
        .then((cs) => setNames(Object.fromEntries(cs.map((c) => [c.stream_id, c.name]))))
        .catch(console.error);
    loadNames();
    const namesTimer = setInterval(loadNames, NAMES_REFRESH_MS);
    api
      .events({ event_type: "ALPR" }, 1, 30)
      .then((page) => setReadings(page.items))
      .catch(console.error);
    return () => clearInterval(namesTimer);
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = () =>
      api
        .alprCameras()
        .then((cs) => {
          if (!alive) return;
          setCameras(cs);
          setError(null);
        })
        .catch((e) => {
          if (alive) setError(String((e as Error).message ?? e));
        });
    tick();
    const timer = setInterval(tick, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const live = cameras.filter((c) => c.status === "live").length;
  const plates = cameras.reduce((n, c) => n + c.detections.length, 0);
  const streaming = new Set(
    cameras
      .filter((c) => inViewIds.has(c.camera_id) && c.camera_id !== maximized)
      .slice(0, MAX_STREAMS)
      .map((c) => c.camera_id),
  );

  const patchReading = (id: string, patch: Partial<EventItem>) => {
    setReadings((prev) => prev.map((r) => (r.event_id === id ? { ...r, ...patch } : r)));
    setSelected((s) => (s && s.event_id === id ? { ...s, ...patch } : s));
  };

  const onAck = (id: string) => {
    api
      .ackEvent(id)
      .then((u) =>
        patchReading(id, { acknowledged_at: u.acknowledged_at, acknowledged_by: u.acknowledged_by }),
      )
      .catch(console.error);
  };

  const onFeedback = (id: string, value: "correct" | "false_positive") => {
    api.setFeedback(id, value).catch(console.error);
  };

  return (
    <div className="flex h-full">
      <div className="min-w-0 flex-1 overflow-y-auto p-5">
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <h1 className="font-display text-xl font-semibold">Matrículas</h1>
          <div className="flex items-center gap-2 font-mono text-[11px] text-mut">
            <Activity size={12} className={error ? "text-crit" : "text-info"} />
            {error
              ? "servicio ALPR sin conexión"
              : `${live}/${cameras.length} en vivo${plates > 0 ? ` · ${plates} placa${plates === 1 ? "" : "s"} en cuadro` : ""}`}
          </div>
        </div>
        {(() => {
          // mismo criterio que En vivo: sin senal al fondo y compactas
          const isOnline = (st: string) =>
            st === "live" || st === "waiting-inference" || st === "connecting";
          const onlineCams = cameras.filter((c) => isOnline(c.status));
          const offlineCams = cameras.filter((c) => !isOnline(c.status));
          return (
            <>
              <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
                {onlineCams.map((c) => (
                  <CameraCard
                    key={c.camera_id}
                    camera={c}
                    name={names[c.camera_id] ?? c.camera_id}
                    active={streaming.has(c.camera_id)}
                    onInView={handleInView}
                    onMaximize={setMaximized}
                  />
                ))}
              </div>
              {offlineCams.length > 0 && (
                <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
                  {offlineCams.map((c) => (
                    <div
                      key={c.camera_id}
                      onClick={() => setMaximized(c.camera_id)}
                      className="flex cursor-pointer items-center gap-2 rounded-lg border border-line/60 bg-panel/60 px-3 py-2.5 transition-colors hover:border-brand/40"
                      role="status"
                    >
                      <CameraOff size={14} className="shrink-0 text-crit" strokeWidth={1.5} />
                      <span className="truncate font-display text-xs text-mut">
                        {names[c.camera_id] ?? c.camera_id}
                      </span>
                      <span className="ml-auto shrink-0 font-mono text-[10px] text-crit">
                        {STATUS_LABEL[c.status] ?? "offline"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          );
        })()}
        {!error && cameras.length === 0 && (
          <p className="mt-6 text-center text-sm text-dim">
            Servicio ALPR sin cámaras configuradas.
          </p>
        )}
      </div>
      <aside className="w-80 shrink-0 overflow-y-auto border-l border-line xl:w-96">
        <h2 className="sticky top-0 z-10 bg-panel px-4 py-3 font-mono text-[11px] uppercase tracking-wider text-mut">
          Lecturas recientes
        </h2>
        <div className="space-y-2 px-3 pb-4">
          {readings.map((r) => {
            const plate = String(r.metadata?.plate_text ?? "—");
            const ocr = Number(r.metadata?.ocr_confidence ?? 0);
            return (
              <div
                key={r.event_id}
                onClick={() => setSelected(r)}
                className="group cursor-pointer rounded-lg border border-line/60 bg-panel/60 p-2.5 transition hover:border-info/50 hover:bg-raised"
              >
                <div className="flex gap-3">
                  {r.snapshot_url ? (
                    <img
                      src={r.snapshot_url}
                      alt="evidencia"
                      className="h-14 w-24 shrink-0 rounded-md border border-line object-cover"
                    />
                  ) : (
                    <div className="h-14 w-24 shrink-0 rounded-md border border-line bg-raised" />
                  )}
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-sm font-semibold tracking-[0.18em] text-ink">
                        {plate}
                      </span>
                      {r.acknowledged_at && (
                        <span className="rounded bg-info/10 px-1 font-mono text-[9px] uppercase text-info">
                          acusada
                        </span>
                      )}
                    </div>
                    {(() => {
                      const v = r.metadata?.vehicle as VehicleInfo | undefined;
                      const summary = v ? [v.make, v.model, v.year].filter(Boolean).join(" ") : "";
                      return summary ? (
                        <div className="truncate text-[11px] text-info">{summary}</div>
                      ) : null;
                    })()}
                    <div className="truncate text-xs text-mut">
                      {names[r.camera_id] ?? r.camera_id.slice(0, 8)} · {fmtDateTime(r.timestamp)}
                    </div>
                    <div className="font-mono text-[11px] text-dim">
                      det {(r.confidence ?? 0).toFixed(2)} · ocr {(ocr * 100).toFixed(0)}%
                    </div>
                  </div>
                  <Maximize2
                    size={13}
                    className="ml-auto shrink-0 self-center text-dim opacity-0 transition group-hover:opacity-100"
                  />
                </div>
              </div>
            );
          })}
        </div>
        {readings.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-mut">
            Sin matrículas legibles todavía.
          </p>
        )}
      </aside>
      {selected && (
        <ReadingDetail
          reading={selected}
          name={names[selected.camera_id] ?? selected.camera_id.slice(0, 8)}
          onClose={() => setSelected(null)}
          onAck={onAck}
          onFeedback={onFeedback}
        />
      )}
      {maximized &&
        (() => {
          const camera = cameras.find((c) => c.camera_id === maximized);
          if (!camera) return null;
          return (
            <CameraModal
              camera={camera}
              name={names[camera.camera_id] ?? camera.camera_id}
              onClose={() => setMaximized(null)}
            />
          );
        })()}
    </div>
  );
}
