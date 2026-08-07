import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import {
  api,
  type Camera,
  type EventFilters,
  type EventItem,
  type EventPage,
} from "../lib/api";
import {
  CLASS_LABELS,
  EVENT_LABELS,
  SEVERITY_CLASSES,
  fmtDateTime,
} from "../lib/format";

const EVENT_TYPES = ["LINE_CROSSING", "STOPPED_VEHICLE", "OBSTRUCTION", "WRONG_WAY", "CONGESTION"];

function Evidence({
  event,
  onAck,
}: {
  event: EventItem;
  onAck: (id: string) => void;
}) {
  return (
    <div className="space-y-2">
      {event.clip_url ? (
        <video src={event.clip_url} controls preload="metadata" className="w-full rounded border border-line" />
      ) : event.snapshot_url ? (
        <img src={event.snapshot_url} alt="evidencia" className="w-full rounded border border-line object-cover" />
      ) : (
        <span className="font-mono text-[11px] text-dim">sin evidencia</span>
      )}
      {event.acknowledged_at ? (
        <p className="font-mono text-[11px] text-info">
          acusada por {event.acknowledged_by}
        </p>
      ) : (
        event.priority !== "info" && (
          <button
            onClick={() => onAck(event.event_id)}
            className="rounded-md border border-line px-3 py-1 text-xs text-mut transition-colors hover:border-info hover:text-info"
          >
            Acusar recibo
          </button>
        )
      )}
    </div>
  );
}

export default function EventsPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [filters, setFilters] = useState<EventFilters>({});
  const [data, setData] = useState<EventPage | null>(null);
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    api.cameras().then(setCameras).catch(console.error);
  }, []);

  useEffect(() => {
    api.events(filters, page).then(setData).catch(console.error);
  }, [filters, page]);

  const camName = (id: string) => cameras.find((c) => c.id === id)?.name ?? id.slice(0, 8);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  const onAck = (eventId: string) => {
    api
      .ackEvent(eventId)
      .then((updated) => {
        setData((prev) =>
          prev
            ? {
                ...prev,
                items: prev.items.map((i) =>
                  i.event_id === eventId
                    ? { ...i, acknowledged_at: updated.acknowledged_at, acknowledged_by: updated.acknowledged_by }
                    : i,
                ),
              }
            : prev,
        );
      })
      .catch(console.error);
  };

  return (
    <div className="space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-display text-xl font-semibold">Eventos</h1>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <select
            value={filters.camera_id ?? ""}
            onChange={(e) => {
              setPage(1);
              setFilters((f) => ({ ...f, camera_id: e.target.value || undefined }));
            }}
            className="rounded-md border border-line bg-panel px-3 py-1.5 text-sm"
          >
            <option value="">Todas las cámaras</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <select
            value={filters.event_type ?? ""}
            onChange={(e) => {
              setPage(1);
              setFilters((f) => ({ ...f, event_type: e.target.value || undefined }));
            }}
            className="rounded-md border border-line bg-panel px-3 py-1.5 text-sm"
          >
            <option value="">Todos los tipos</option>
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {EVENT_LABELS[t]}
              </option>
            ))}
          </select>
          <select
            value={filters.priority ?? ""}
            onChange={(e) => {
              setPage(1);
              setFilters((f) => ({ ...f, priority: e.target.value || undefined }));
            }}
            className="rounded-md border border-line bg-panel px-3 py-1.5 text-sm"
          >
            <option value="">Toda prioridad</option>
            <option value="info">info</option>
            <option value="warning">warning</option>
            <option value="critical">critical</option>
          </select>
          <label className="flex items-center gap-1.5 text-sm text-mut">
            <input
              type="checkbox"
              checked={filters.pending_only ?? false}
              onChange={(e) => {
                setPage(1);
                setFilters((f) => ({ ...f, pending_only: e.target.checked || undefined }));
              }}
            />
            sin acusar
          </label>
          <button
            onClick={() => void api.download(`/api/v1/reports/events.csv?${new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][])}`, "eventos.csv")}
            className="flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm text-mut transition-colors hover:text-ink"
          >
            <Download size={14} /> CSV
          </button>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-line">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line bg-panel text-left font-mono text-[11px] uppercase tracking-wider text-mut">
              <th className="px-4 py-2.5">Fecha</th>
              <th className="px-4 py-2.5">Cámara</th>
              <th className="px-4 py-2.5">Evento</th>
              <th className="px-4 py-2.5">Prioridad</th>
              <th className="px-4 py-2.5">Clase</th>
              <th className="px-4 py-2.5 text-right">Conf.</th>
            </tr>
          </thead>
          <tbody>
            {data?.items.map((e) => {
              const cls = String(e.metadata?.vehicle_class ?? "");
              const isOpen = expanded === e.event_id;
              return [
                <tr
                  key={e.event_id}
                  onClick={() => setExpanded(isOpen ? null : e.event_id)}
                  className="cursor-pointer border-b border-line/50 transition-colors hover:bg-raised/50"
                >
                  <td className="px-4 py-2.5 font-mono text-xs text-mut">
                    {fmtDateTime(e.timestamp)}
                  </td>
                  <td className="px-4 py-2.5">{camName(e.camera_id)}</td>
                  <td className="px-4 py-2.5">{EVENT_LABELS[e.event_type] ?? e.event_type}</td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${SEVERITY_CLASSES[e.priority]}`}
                    >
                      {e.priority}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-mut">{CLASS_LABELS[cls] ?? "—"}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-xs text-mut">
                    {e.confidence?.toFixed(2) ?? "—"}
                  </td>
                </tr>,
                isOpen && (
                  <tr key={`${e.event_id}-detail`} className="border-b border-line/50 bg-panel/60">
                    <td colSpan={6} className="px-4 py-3">
                      <div className="flex gap-4">
                        <div className="w-72 shrink-0">
                          <Evidence event={e} onAck={onAck} />
                        </div>
                        <pre className="min-w-0 flex-1 overflow-x-auto font-mono text-[11px] leading-relaxed text-mut">
                          {JSON.stringify(e.metadata, null, 2)}
                        </pre>
                      </div>
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
        {data && data.items.length === 0 && (
          <p className="px-4 py-10 text-center text-sm text-mut">
            Sin eventos para los filtros seleccionados
          </p>
        )}
      </div>

      {data && pages > 1 && (
        <div className="flex items-center justify-between font-mono text-xs text-mut">
          <span>
            {data.total} eventos · página {data.page}/{pages}
          </span>
          <div className="flex gap-2">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="rounded border border-line px-3 py-1 disabled:opacity-40"
            >
              anterior
            </button>
            <button
              disabled={page >= pages}
              onClick={() => setPage((p) => p + 1)}
              className="rounded border border-line px-3 py-1 disabled:opacity-40"
            >
              siguiente
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
