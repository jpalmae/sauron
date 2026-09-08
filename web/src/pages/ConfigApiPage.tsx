import { Save } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type AlprConfig } from "../lib/api";

const PROVIDERS = [
  { value: "", label: "— desactivado —" },
  { value: "demo", label: "Demo (datos sintéticos locales)" },
  { value: "boostr", label: "Boostr.cl (REST, JSON)" },
  { value: "matriculaapi", label: "MatriculaAPI (SOAP regcheck)" },
  { value: "autoriesgo", label: "AutoRiesgo.cl (REST, X-Api-Key)" },
];

export default function ConfigApiPage() {
  const [cfg, setCfg] = useState<AlprConfig>({});
  const [lookups, setLookups] = useState<Record<string, number>>({});
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .alprConfig()
      .then((c) => setCfg(c))
      .catch(console.error);
    api
      .alprHealth()
      .then((h) => setLookups(h.vehicle_lookups ?? {}))
      .catch(console.error);
    const timer = setInterval(
      () =>
        api
          .alprHealth()
          .then((h) => setLookups(h.vehicle_lookups ?? {}))
          .catch(() => {}),
      5000,
    );
    return () => clearInterval(timer);
  }, []);

  const set = (patch: Partial<AlprConfig>) => setCfg((c) => ({ ...c, ...patch }));

  const save = async () => {
    setBusy(true);
    try {
      await api.saveAlprConfig(cfg);
      setSavedAt(new Date().toLocaleTimeString("es-CL", { hour12: false }));
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  };

  const field =
    "rounded-md border border-line bg-base px-3 py-2 text-sm text-ink placeholder:text-dim";

  return (
    <div className="h-full overflow-y-auto p-5">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="font-display text-xl font-semibold">Config API — Matrículas</h1>
        <span className="font-mono text-[11px] text-mut">
          consultas: {lookups.attempts ?? 0} intentos · {lookups.ok ?? 0} con datos ·{" "}
          {lookups.timeout ?? 0} timeout · {lookups.empty ?? 0} vacías
        </span>
      </div>

      <div className="max-w-3xl space-y-5">
        <section className="rounded-lg border border-line bg-panel p-4">
          <h2 className="mb-3 font-mono text-[11px] uppercase tracking-wider text-mut">
            Proveedor de datos
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-mut">
              Proveedor
              <select
                value={cfg.provider ?? ""}
                onChange={(e) => set({ provider: e.target.value })}
                className={`${field} mt-1 w-full`}
              >
                {PROVIDERS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-mut">
              URL del endpoint (con {"{plate}"})
              <input
                value={cfg.api_url ?? ""}
                onChange={(e) => set({ api_url: e.target.value })}
                placeholder="https://www.regcheck.org.uk/api/reg.asmx"
                className={`${field} mt-1 w-full font-mono`}
              />
            </label>
          </div>

          {(cfg.provider === "autoriesgo" || cfg.ar_api_key) && (
            <label className="mt-3 block text-xs text-mut">
              API Key AutoRiesgo (X-Api-Key)
              <input
                value={cfg.ar_api_key ?? ""}
                onChange={(e) => set({ ar_api_key: e.target.value })}
                className={`${field} mt-1 w-full font-mono`}
              />
            </label>
          )}

          {(cfg.provider === "boostr" || cfg.api_key) && (
            <label className="mt-3 block text-xs text-mut">
              API Key (Boostr)
              <input
                value={cfg.api_key ?? ""}
                onChange={(e) => set({ api_key: e.target.value })}
                className={`${field} mt-1 w-full font-mono`}
              />
            </label>
          )}

          {cfg.provider === "matriculaapi" && (
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <label className="text-xs text-mut">
                Usuario
                <input
                  value={cfg.username ?? ""}
                  onChange={(e) => set({ username: e.target.value })}
                  className={`${field} mt-1 w-full font-mono`}
                />
              </label>
              <label className="text-xs text-mut">
                License Key
                <input
                  type="password"
                  value={cfg.license_key ?? ""}
                  onChange={(e) => set({ license_key: e.target.value })}
                  className={`${field} mt-1 w-full font-mono`}
                />
              </label>
              <label className="text-xs text-mut">
                Operación
                <input
                  value={cfg.operation ?? "CheckChile"}
                  onChange={(e) => set({ operation: e.target.value })}
                  className={`${field} mt-1 w-full font-mono`}
                />
              </label>
            </div>
          )}
        </section>

        <section className="rounded-lg border border-line bg-panel p-4">
          <h2 className="mb-3 font-mono text-[11px] uppercase tracking-wider text-mut">
            Reglas de consulta y publicación
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs text-mut">
              Certeza mínima de detección (YOLO) para consultar
              <input
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={cfg.query_det_conf ?? 1}
                onChange={(e) => set({ query_det_conf: Number(e.target.value) })}
                className={`${field} mt-1 w-full`}
              />
            </label>
            <label className="text-xs text-mut">
              Certeza mínima de OCR para consultar
              <input
                type="number"
                step="0.01"
                min="0"
                max="1"
                value={cfg.query_ocr_conf ?? 1}
                onChange={(e) => set({ query_ocr_conf: Number(e.target.value) })}
                className={`${field} mt-1 w-full`}
              />
            </label>
            <label className="text-xs text-mut sm:col-span-2">
              Cámaras autorizadas a consultar (separadas por coma, vacío = todas)
              <input
                value={cfg.cameras ?? ""}
                onChange={(e) => set({ cameras: e.target.value })}
                placeholder="cam-214"
                className={`${field} mt-1 w-full font-mono`}
              />
            </label>
            <label className="text-xs text-mut">
              Región fija (vacío = la adivina el OCR)
              <input
                value={cfg.region ?? ""}
                onChange={(e) => set({ region: e.target.value })}
                placeholder="CL"
                className={`${field} mt-1 w-full`}
              />
            </label>
          </div>
          <div className="mt-3 flex flex-wrap gap-4 text-sm text-mut">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={cfg.validate_plate ?? false}
                onChange={(e) => set({ validate_plate: e.target.checked })}
              />
              Publicar solo placas validadas por el Registro Civil
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={cfg.include_owner ?? false}
                onChange={(e) => set({ include_owner: e.target.checked })}
              />
              Incluir dueño (nombre + RUT)
            </label>
          </div>
        </section>

        <div className="flex items-center gap-3">
          <button
            onClick={save}
            disabled={busy}
            className="flex items-center gap-1.5 rounded-md bg-brand px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            <Save size={14} /> Guardar configuración
          </button>
          {savedAt && (
            <span className="font-mono text-[11px] text-info">
              guardado {savedAt} · se aplica en ~15 s
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
