import { Pencil, Plus, Route, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Camera } from "../lib/api";
import { DOMAIN_COLOR, filterCamerasByDomain, getCameraDomain, type Domain } from "../lib/domain";

interface Draft {
  name: string;
  stream_id: string;
  rtsp_url: string;
  domain: Domain;
}

const EMPTY: Draft = { name: "", stream_id: "", rtsp_url: "", domain: "traffic" as Domain };

function CameraForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: Draft;
  onSave: (d: Draft) => Promise<void>;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await onSave(draft);
        } finally {
          setBusy(false);
        }
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
        placeholder="rtsp://usuario:clave@host:554/…"
        value={draft.rtsp_url}
        onChange={(e) => setDraft({ ...draft, rtsp_url: e.target.value })}
        className="w-full rounded-md border border-line bg-base px-3 py-2 font-mono text-sm"
      />
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-50"
        >
          Guardar
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
  const filteredCameras = domainFilter ? filterCamerasByDomain(cameras, domainFilter) : cameras;

  const reload = () => api.cameras().then(setCameras).catch(console.error);
  useEffect(() => {
    void reload();
  }, []);

  return (
    <div className="space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-display text-xl font-semibold">Cámaras</h1>
        <div className="flex overflow-hidden rounded-md border border-line">
          {([null, "traffic", "people"] as const).map((d) => (
            <button
              key={String(d)}
              onClick={() => setDomainFilter(d)}
              className={`px-3 py-1.5 text-xs ${domainFilter === d ? "bg-raised text-ink" : "text-mut hover:text-ink"}`}
            >
              {d === null ? "Todas" : d === "traffic" ? "Tráfico" : "Personas"}
            </button>
          ))}
        </div>
        <button
          onClick={() => setCreating(true)}
          className="ml-auto flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white"
        >
          <Plus size={14} /> Nueva cámara
        </button>
      </div>

      {creating && (
        <div className="rounded-lg border border-line bg-panel p-4">
          <CameraForm
            initial={EMPTY}
            onSave={async (d) => {
              const { domain, ...rest } = d;
              await api.createCamera({ ...rest, analytics_profile: domain });
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
                  <button
                    onClick={async () => {
                      await api.updateCamera(c.id, { is_active: !c.is_active });
                      await reload();
                    }}
                    className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${
                      c.is_active
                        ? "border-info/40 bg-info/10 text-info"
                        : "border-line text-dim"
                    }`}
                  >
                    {c.is_active ? "activa" : "inactiva"}
                  </button>
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
                      onSave={async (d) => {
                        const { domain, ...rest } = d;
                        await api.updateCamera(c.id, { ...rest, analytics_profile: domain });
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
