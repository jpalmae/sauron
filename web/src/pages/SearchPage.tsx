import { Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Camera, type EventItem } from "../lib/api";
import { isPeopleEvent, isTrafficEvent, type Domain } from "../lib/domain";
import { EVENT_LABELS, SEVERITY_CLASSES, fmtDateTime } from "../lib/format";

export default function SearchPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<string | null>(null);
  const [domain, setDomain] = useState<Domain | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ distance: number; event: EventItem }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState(false);
  const filteredResults = domain
    ? results.filter((r) => (domain === "traffic" ? isTrafficEvent(r.event) : isPeopleEvent(r.event)))
    : results;

  useEffect(() => {
    api.cameras().then(setCameras).catch(console.error);
  }, []);

  const run = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await api.search(query, cameraId ?? undefined);
      setResults(resp.results);
      setSearched(true);
    } catch (err) {
      setError(String(err));
      setResults([]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4 p-5">
      <h1 className="font-display text-xl font-semibold">Búsqueda semántica</h1>
      <form onSubmit={run} className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-64 flex-1">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-dim" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder='p. ej. "camión rojo", "persona caída", "bus amarillo"…'
            className="w-full rounded-md border border-line bg-panel py-2 pl-9 pr-3 text-sm"
          />
        </div>
        <div className="flex overflow-hidden rounded-md border border-line">
          {([null, "traffic", "people"] as const).map((d) => (
            <button
              key={String(d)}
              type="button"
              onClick={() => setDomain(d)}
              className={`px-3 py-2 text-xs ${domain === d ? "bg-raised text-ink" : "text-mut hover:text-ink"}`}
            >
              {d === null ? "Todo" : d === "traffic" ? "Tráfico" : "Personas"}
            </button>
          ))}
        </div>
        <select
          value={cameraId ?? ""}
          onChange={(e) => setCameraId(e.target.value || null)}
          className="rounded-md border border-line bg-panel px-3 py-2 text-sm"
        >
          <option value="">Todas las cámaras</option>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "Buscando…" : "Buscar"}
        </button>
      </form>

      {error && (
        <p className="rounded-md border border-crit/40 bg-crit/10 px-4 py-2 font-mono text-xs text-crit">
          {error}
        </p>
      )}

      {searched && filteredResults.length === 0 && !error && (
        <p className="text-sm text-mut">
          Sin resultados{domain ? ` en ${domain === "traffic" ? "tráfico" : "personas"}` : ""} con evidencia indexada.
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        {filteredResults.map(({ distance, event }) => (
          <Link
            to="/events"
            key={event.event_id}
            className="group overflow-hidden rounded-lg border border-line bg-panel transition-colors hover:border-brand"
          >
            {event.snapshot_url ? (
              <img
                src={event.snapshot_url}
                alt="evidencia"
                className="aspect-video w-full object-cover"
              />
            ) : (
              <div className="grid aspect-video w-full place-items-center font-mono text-[10px] text-dim">
                sin imagen
              </div>
            )}
            <div className="p-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="font-display text-xs font-medium">
                  {EVENT_LABELS[event.event_type] ?? event.event_type}
                </span>
                <span
                  className={`rounded-full border px-1.5 font-mono text-[9px] ${SEVERITY_CLASSES[event.priority]}`}
                >
                  {event.priority}
                </span>
              </div>
              <div className="mt-1 flex items-center justify-between font-mono text-[10px] text-mut">
                <span>{fmtDateTime(event.timestamp)}</span>
                <span title="distancia semántica (menor = más similar)">
                  d={distance.toFixed(2)}
                </span>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
