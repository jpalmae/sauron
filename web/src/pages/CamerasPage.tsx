import { Activity, CircleCheck, CircleX, LoaderCircle, Pencil, Plus, Radar, Route, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, auth, type Camera, type CameraProbe, type OnvifDevice } from "../lib/api";
import { DOMAIN_COLOR, filterCamerasByDomain, getCameraDomain, type Domain } from "../lib/domain";

interface Draft {
  name: string;
  stream_id: string;
  rtsp_url: string;
  domain: Domain;
}

const EMPTY: Draft = { name: "", stream_id: "", rtsp_url: "", domain: "traffic" as Domain };

const SIGNAL_REFRESH_MS = 5000;

interface DsHealth {
  cameras?: Record<string, { state?: string }>;
}

interface AlprHealth {
  cameras?: { camera_id: string; status: string }[];
}

const CONNECTING_STATES = new Set(["starting", "recovering", "waiting-inference", "connecting"]);

function useSignalStatus() {
  const [ds, setDs] = useState<Record<string, string>>({});
  const [alpr, setAlpr] = useState<Record<string, string>>({});
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const headers: Record<string, string> = auth.token()
        ? { Authorization: `Bearer ${auth.token()}` }
        : {};
      try {
        // DeepStream responde 503 (con JSON válido) cuando hay cámaras caídas.
        const r = await fetch("/deepstream/healthz", { headers });
        if (r.status === 200 || r.status === 503) {
          const d: DsHealth = await r.json();
          const map: Record<string, string> = {};
          for (const [k, v] of Object.entries(d.cameras ?? {})) map[k] = v.state ?? "";
          if (alive) setDs(map);
        }
      } catch {
        /* motor sin respuesta: conserva el último estado */
      }
      try {
        const r = await fetch("/alpr/healthz", { headers });
        if (r.ok) {
          const d: AlprHealth = await r.json();
          const map: Record<string, string> = {};
          for (const c of d.cameras ?? []) map[c.camera_id] = c.status;
          if (alive) setAlpr(map);
        }
      } catch {
        /* ídem */
      }
    };
    tick();
    const timer = setInterval(tick, SIGNAL_REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  return { ds, alpr };
}

function signalFor(
  cam: Camera,
  ds: Record<string, string>,
  alpr: Record<string, string>,
): { label: string; cls: string } {
  const dsState = ds[cam.stream_id] ?? "";
  const alprStatus = alpr[cam.stream_id] ?? "";
  if (dsState === "live" || alprStatus === "live") {
    return { label: "en vivo", cls: "border-info/40 bg-info/10 text-info" };
  }
  if (!cam.is_active) {
    return { label: "inactiva", cls: "border-line text-dim" };
  }
  if (CONNECTING_STATES.has(dsState) || CONNECTING_STATES.has(alprStatus)) {
    return { label: "conectando", cls: "border-warn/40 bg-warn/10 text-warn" };
  }
  return { label: "sin señal", cls: "border-crit/40 bg-crit/10 text-crit" };
}

function CameraForm({
  initial,
  initialProbe,
  onSave,
  onCancel,
}: {
  initial: Draft;
  initialProbe?: CameraProbe | null;
  onSave: (d: Draft, activate: boolean) => Promise<void>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<CameraProbe | null>(initialProbe ?? null);
  const [error, setError] = useState("");

  const save = async (activate: boolean) => {
    if (!draft.name.trim() || !draft.stream_id.trim() || !draft.rtsp_url.trim()) {
      setError("Completa nombre, stream_id y URL antes de guardar.");
      return;
    }
    if (activate && probe?.status !== "ok") {
      setError("Prueba la conexión correctamente antes de activar la cámara.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onSave(draft, activate);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible guardar la cámara");
    } finally {
      setBusy(false);
    }
  };

  const testConnection = async () => {
    setProbing(true);
    setError("");
    try {
      const result = await api.probeCameraUrl(draft.rtsp_url);
      setProbe(result);
      if (result.status !== "ok") setError(result.error ?? "No fue posible abrir el video");
    } catch (reason) {
      setProbe(null);
      setError(reason instanceof Error ? reason.message : "No fue posible probar la cámara");
    } finally {
      setProbing(false);
    }
  };
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        await save(true);
      }}
    >
      <div className="grid grid-cols-2 gap-2">
        <input
          required
          placeholder="Nombre (p. ej. Entrada Norte)"
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          className="rounded-md border border-line bg-base px-3 py-2 text-sm"
        />
        <select
          value={draft.domain}
          onChange={(e) => setDraft({ ...draft, domain: e.target.value as Domain })}
          className="rounded-md border border-line bg-base px-3 py-2 text-sm"
        >
          <option value="traffic">🚗 Tráfico</option>
          <option value="people">🧍 Personas</option>
          <option value="matriculas">🔢 Matrículas</option>
          <option value="streaming">📺 Streaming</option>
        </select>
      </div>
      <input
        required
        placeholder="stream_id (p. ej. cam-01)"
        value={draft.stream_id}
        onChange={(e) => setDraft({ ...draft, stream_id: e.target.value })}
        className="w-full rounded-md border border-line bg-base px-3 py-2 font-mono text-sm"
      />
      <input
        required
        placeholder="rtsp://usuario:clave@host:554/…"
        value={draft.rtsp_url}
        onChange={(e) => {
          setDraft({ ...draft, rtsp_url: e.target.value });
          setProbe(null);
          setError("");
        }}
        className="w-full rounded-md border border-line bg-base px-3 py-2 font-mono text-sm"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void testConnection()}
          disabled={probing || !draft.rtsp_url}
          className="flex items-center gap-1.5 rounded-md border border-line px-3 py-2 text-sm text-mut hover:text-ink disabled:opacity-50"
        >
          {probing ? <LoaderCircle size={14} className="animate-spin" /> : <Activity size={14} />}
          Probar conexión
        </button>
        {probe?.status === "ok" && (
          <span className="flex items-center gap-1 font-mono text-xs text-info">
            <CircleCheck size={14} /> {probe.codec?.toUpperCase()} · {probe.width}×{probe.height} · {probe.fps} FPS · {probe.latency_ms} ms
          </span>
        )}
        {error && (
          <span className="flex items-center gap-1 text-xs text-crit"><CircleX size={14} /> {error}</span>
        )}
      </div>
      {probe?.preview_jpeg && (
        <img
          src={`data:image/jpeg;base64,${probe.preview_jpeg}`}
          alt="Preview de la cámara"
          className="max-h-72 w-full rounded-md border border-line bg-black object-contain"
        />
      )}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy || probe?.status !== "ok"}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-50"
        >
          Guardar y activar
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void save(false)}
          title="Guarda la configuración sin incorporarla todavía al pipeline"
          className="rounded-md border border-line px-4 py-2 text-sm text-mut hover:text-ink disabled:opacity-50"
        >
          Guardar inactiva
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-line px-4 py-2 text-sm text-mut hover:text-ink"
        >
          Cancelar
        </button>
      </div>
    </form>
  );
}

export default function CamerasPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [domainFilter, setDomainFilter] = useState<Domain | null>(null);
  const [newDraft, setNewDraft] = useState<Draft>(EMPTY);
  const [discovering, setDiscovering] = useState(false);
  const [onvifDevices, setOnvifDevices] = useState<OnvifDevice[]>([]);
  const [discoveryDone, setDiscoveryDone] = useState(false);
  const [probingCamera, setProbingCamera] = useState<string | null>(null);
  const filteredCameras = domainFilter ? filterCamerasByDomain(cameras, domainFilter) : cameras;
  const { ds, alpr } = useSignalStatus();

  const reload = () => api.cameras().then(setCameras).catch(console.error);
  useEffect(() => {
    void reload();
  }, []);

  return (
    <div className="space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-display text-xl font-semibold">Cámaras</h1>
        <div className="flex overflow-hidden rounded-md border border-line">
          {([null, "traffic", "people", "matriculas", "streaming"] as const).map((d) => (
            <button
              key={String(d)}
              onClick={() => setDomainFilter(d)}
              className={`px-3 py-1.5 text-xs ${domainFilter === d ? "bg-raised text-ink" : "text-mut hover:text-ink"}`}
            >
              {d === null
                ? "Todas"
                : d === "traffic"
                  ? "Tráfico"
                  : d === "people"
                    ? "Personas"
                    : d === "matriculas"
                      ? "Matrículas"
                      : "Streaming"}
            </button>
          ))}
        </div>
        <button
          onClick={async () => {
            setDiscovering(true);
            setDiscoveryDone(false);
            try {
              setOnvifDevices(await api.discoverOnvif());
            } catch (error) {
              console.error(error);
              setOnvifDevices([]);
            } finally {
              setDiscovering(false);
              setDiscoveryDone(true);
            }
          }}
          className="ml-auto flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm text-mut hover:text-ink"
        >
          {discovering ? <LoaderCircle size={14} className="animate-spin" /> : <Radar size={14} />}
          Descubrir ONVIF
        </button>
        <button
          onClick={() => {
            setNewDraft(EMPTY);
            setCreating(true);
          }}
          className="flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white"
        >
          <Plus size={14} /> Nueva cámara
        </button>
      </div>

      {onvifDevices.length > 0 && (
        <div className="rounded-lg border border-line bg-panel p-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="font-display text-sm font-semibold">Dispositivos ONVIF encontrados</h2>
              <p className="mt-0.5 text-xs text-mut">Selecciona el host y completa la ruta RTSP indicada por el fabricante.</p>
            </div>
            <button onClick={() => setOnvifDevices([])} className="text-xs text-mut hover:text-ink">cerrar</button>
          </div>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {onvifDevices.map((device) => (
              <button
                key={device.endpoint}
                onClick={() => {
                  const slug = device.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || `cam-${device.ip.replaceAll(".", "-")}`;
                  setNewDraft({ name: device.name, stream_id: slug, rtsp_url: `rtsp://${device.ip}:554/`, domain: "traffic" });
                  setCreating(true);
                }}
                className="rounded-md border border-line bg-base p-3 text-left hover:border-brand/60"
              >
                <div className="font-medium">{device.name}</div>
                <div className="mt-1 font-mono text-xs text-mut">{device.ip}</div>
                {device.location && <div className="mt-1 text-xs text-dim">{device.location}</div>}
              </button>
            ))}
          </div>
        </div>
      )}

      {discoveryDone && onvifDevices.length === 0 && (
        <div className="flex items-center justify-between border-y border-line bg-panel/50 px-4 py-3 text-sm">
          <span className="text-mut">No se encontraron cámaras ONVIF en la red local. Puedes agregarlas mediante su URL RTSP.</span>
          <button onClick={() => setDiscoveryDone(false)} className="text-xs text-mut hover:text-ink">cerrar</button>
        </div>
      )}

      {creating && (
        <div className="rounded-lg border border-line bg-panel p-4">
          <CameraForm
            initial={newDraft}
            onSave={async (d, activate) => {
              const { domain, ...rest } = d;
              const camera = await api.createCamera({ ...rest, analytics_profile: domain, is_active: false });
              if (activate) {
                const result = await api.probeCamera(camera.id);
                if (result.status !== "ok") {
                  await api.deleteCamera(camera.id);
                  throw new Error(result.error ?? "La cámara no superó la validación final");
                }
                await api.updateCamera(camera.id, { is_active: true });
              }
              setCreating(false);
              await reload();
            }}
            onCancel={() => setCreating(false)}
          />
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-line">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line bg-panel text-left font-mono text-[11px] uppercase tracking-wider text-mut">
              <th className="px-4 py-2.5">Nombre</th>
              <th className="px-4 py-2.5">stream_id</th>
              <th className="px-4 py-2.5">Dominio</th>
              <th className="px-4 py-2.5">ROI</th>
              <th className="px-4 py-2.5">Pipeline</th>
              <th className="px-4 py-2.5">Estado</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {filteredCameras.map((c) => {
              const d = getCameraDomain(c);
              return [
                <tr key={c.id} className="border-b border-line/50">
                  <td className="px-4 py-2.5 font-medium">{c.name}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-mut">{c.stream_id}</td>
                  <td className="px-4 py-2.5">
                    <select
                      value={d}
                      onChange={async (e) => {
                        const nd = e.target.value as Domain;
                        await api.updateCamera(c.id, { analytics_profile: nd });
                        await reload();
                      }}
                      className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${DOMAIN_COLOR[d]}`}
                    >
                      <option value="traffic">Tráfico</option>
                      <option value="people">Personas</option>
                      <option value="matriculas">Matrículas</option>
                      <option value="streaming">Streaming</option>
                    </select>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-mut">
                    {c.roi_config
                      ? `${c.roi_config.lines?.length ?? 0} líneas · ${c.roi_config.polygons?.length ?? 0} polígonos`
                      : "sin configurar"}
                  </td>
                <td className="px-4 py-2.5">
                  <span className="rounded border border-line bg-base px-2 py-1 font-mono text-[10px] text-mut">
                    DeepStream · NvDCF
                  </span>
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex flex-wrap gap-1">
                    <button
                      title={!c.is_active && c.probe_status !== "ok" ? "Prueba el video antes de activar" : undefined}
                      disabled={!c.is_active && c.probe_status !== "ok"}
                      onClick={async () => {
                        await api.updateCamera(c.id, { is_active: !c.is_active });
                        await reload();
                      }}
                      className={`rounded-full border px-2 py-0.5 font-mono text-[10px] disabled:cursor-not-allowed disabled:opacity-50 ${
                        c.is_active
                          ? "border-info/40 bg-info/10 text-info"
                          : "border-line text-dim"
                      }`}
                    >
                      {c.is_active ? "activa" : "inactiva"}
                    </button>
                    {(() => {
                      const signal = signalFor(c, ds, alpr);
                      return (
                        <span
                          className={`rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase ${signal.cls}`}
                        >
                          {signal.label}
                        </span>
                      );
                    })()}
                    <span
                      title={c.probe_details?.error ?? `Última prueba: ${c.last_probe_at ?? "nunca"}`}
                      className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${
                        c.probe_status === "ok"
                          ? "border-info/40 bg-info/10 text-info"
                          : c.probe_status === "failed"
                            ? "border-crit/40 bg-crit/10 text-crit"
                            : "border-line text-dim"
                      }`}
                    >
                      video {c.probe_status === "ok" ? "OK" : c.probe_status === "failed" ? "ERROR" : "sin probar"}
                    </span>
                    <span className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${c.roi_config ? "border-info/40 text-info" : "border-warn/40 text-warn"}`}>
                      ROI {c.roi_config ? "OK" : "pendiente"}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center justify-end gap-1">
                    <Link
                      to={`/cameras/${c.id}/roi`}
                      title="Configurar ROI"
                      className="rounded p-1.5 text-mut hover:bg-raised hover:text-ink"
                    >
                      <Route size={15} />
                    </Link>
                    <button
                      title="Probar conexión"
                      disabled={probingCamera === c.id}
                      onClick={async () => {
                        setProbingCamera(c.id);
                        try {
                          await api.probeCamera(c.id);
                          await reload();
                        } finally {
                          setProbingCamera(null);
                        }
                      }}
                      className="rounded p-1.5 text-mut hover:bg-raised hover:text-ink disabled:opacity-50"
                    >
                      {probingCamera === c.id ? <LoaderCircle size={15} className="animate-spin" /> : <Activity size={15} />}
                    </button>
                    <button
                      title="Editar"
                      onClick={() => setEditing(editing === c.id ? null : c.id)}
                      className="rounded p-1.5 text-mut hover:bg-raised hover:text-ink"
                    >
                      <Pencil size={15} />
                    </button>
                    {confirmDelete === c.id ? (
                      <button
                        onClick={async () => {
                          await api.deleteCamera(c.id);
                          setConfirmDelete(null);
                          await reload();
                        }}
                        className="rounded border border-crit/40 px-2 py-1 font-mono text-[10px] text-crit"
                      >
                        confirmar
                      </button>
                    ) : (
                      <button
                        title="Eliminar"
                        onClick={() => setConfirmDelete(c.id)}
                        className="rounded p-1.5 text-mut hover:bg-raised hover:text-crit"
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>,
              editing === c.id && (
                <tr key={`${c.id}-edit`} className="border-b border-line/50 bg-panel/60">
                  <td colSpan={7} className="px-4 py-3">
                    <CameraForm
                      initial={{ name: c.name, stream_id: c.stream_id, rtsp_url: c.rtsp_url, domain: getCameraDomain(c) }}
                      initialProbe={c.probe_status === "ok" ? c.probe_details : null}
                      onSave={async (d, activate) => {
                        const { domain, ...rest } = d;
                        await api.updateCamera(c.id, { ...rest, analytics_profile: domain, is_active: false });
                        if (activate) {
                          const result = await api.probeCamera(c.id);
                          if (result.status !== "ok") throw new Error(result.error ?? "La cámara no superó la validación final");
                          await api.updateCamera(c.id, { is_active: true });
                        }
                        setEditing(null);
                        await reload();
                      }}
                      onCancel={() => setEditing(null)}
                    />
                  </td>
                </tr>
              )
              ];
            })}
          </tbody>
        </table>
        {filteredCameras.length === 0 && (
          <p className="px-4 py-10 text-center text-sm text-mut">
            {cameras.length === 0
              ? "Aún no hay cámaras. Crea la primera para comenzar."
              : `Sin cámaras de ${domainFilter === "traffic" ? "tráfico" : "personas"}. Cambia el filtro o crea una.`}
          </p>
        )}
      </div>
    </div>
  );
}
