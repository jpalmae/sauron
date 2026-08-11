import { useEffect, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { api, type EngineConfig } from "../lib/api";

const BACKENDS = ["tensorrt", "pose_objects", "pose", "onnx", "mock"];
const MODELS = ["yolov8n", "yolov8s", "yolov8m", "yolov8s-1280", "yolov8m-1280", "yolo11n", "yolo11s"];

export default function EnginePage() {
  const [cfg, setCfg] = useState<EngineConfig | null>(null);
  const [classesText, setClassesText] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const load = () =>
    api
      .pipelineConfig()
      .then((d) => {
        setCfg(d);
        const c = (d.defaults.classes ?? {}) as Record<string, string>;
        setClassesText(Object.entries(c).map(([k, v]) => `${k}: ${v}`).join("\n"));
      })
      .catch(console.error);

  useEffect(() => {
    load();
  }, []);

  const set = (path: string, value: unknown) =>
    setCfg((prev) => {
      if (!prev) return prev;
      const d = structuredClone(prev.defaults as Record<string, unknown>);
      const parts = path.split(".");
      let cur: Record<string, unknown> = d;
      for (let i = 0; i < parts.length - 1; i++) {
        cur[parts[i]] = (cur[parts[i]] as Record<string, unknown>) ?? {};
        cur = cur[parts[i]] as Record<string, unknown>;
      }
      cur[parts[parts.length - 1]] = value;
      return { ...prev, defaults: d };
    });

  const save = async () => {
    if (!cfg) return;
    setSaving(true);
    setMsg("");
    const classes: Record<string, string> = {};
    for (const line of classesText.split("\n")) {
      const m = line.match(/^\s*(\d+)\s*:\s*(.+?)\s*$/);
      if (m) classes[m[1]] = m[2];
    }
    const defaults = { ...(cfg.defaults as Record<string, unknown>), classes };
    try {
      await api.updatePipelineConfig({ defaults, target_fps: cfg.target_fps });
      setMsg("Guardado. La inferencia se recarga en ~15s.");
      load();
    } catch (e) {
      setMsg(`Error: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  if (!cfg) return <div className="p-6 text-mut">cargando…</div>;
  const d = cfg.defaults as Record<string, unknown>;
  const det = (d.detector ?? {}) as Record<string, unknown>;

  return (
    <div className="mx-auto max-w-2xl p-6">
      <div className="mb-4 flex items-center gap-2">
        <SlidersHorizontal size={20} className="text-info" />
        <h1 className="font-display text-xl font-semibold">Configuración del engine</h1>
      </div>
      <p className="mb-5 text-sm text-mut">
        Modelo, clases y umbrales de detección. Al guardar, la inferencia recarga en caliente.
      </p>

      <div className="space-y-4 rounded-lg border border-line bg-panel p-5">
        <Field label="Detector backend">
          <select
            className="w-full rounded-md border border-line bg-base px-3 py-2 text-sm text-ink outline-none focus:border-info"
            value={String(det.backend ?? "pose_objects")}
            onChange={(e) => set("detector.backend", e.target.value)}
          >
            {BACKENDS.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        </Field>

        <Field label="Modelo (catálogo, para backend onnx)">
          <select
            className="w-full rounded-md border border-line bg-base px-3 py-2 text-sm text-ink outline-none focus:border-info"
            value={String(d.model ?? "yolov8s")}
            onChange={(e) => set("model", e.target.value)}
          >
            {MODELS.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </Field>

        <div className="grid grid-cols-3 gap-3">
          <Field label="Confianza">
            <input
              className="w-full rounded-md border border-line bg-base px-3 py-2 text-sm text-ink outline-none focus:border-info"
              type="number" step="0.05" min="0" max="1"
              value={Number(d.confidence_threshold ?? 0.4)}
              onChange={(e) => set("confidence_threshold", parseFloat(e.target.value))}
            />
          </Field>
          <Field label="NMS">
            <input
              className="w-full rounded-md border border-line bg-base px-3 py-2 text-sm text-ink outline-none focus:border-info"
              type="number" step="0.05" min="0" max="1"
              value={Number(d.nms_threshold ?? 0.45)}
              onChange={(e) => set("nms_threshold", parseFloat(e.target.value))}
            />
          </Field>
          <Field label="Target FPS">
            <input
              className="w-full rounded-md border border-line bg-base px-3 py-2 text-sm text-ink outline-none focus:border-info"
              type="number" step="1" min="1" max="30"
              value={cfg.target_fps}
              onChange={(e) => setCfg({ ...cfg, target_fps: parseInt(e.target.value) || 5 })}
            />
          </Field>
        </div>

        <Field label="Clases (una por línea, id: nombre)">
          <textarea
            className="w-full rounded-md border border-line bg-base px-3 py-2 font-mono text-xs text-ink outline-none focus:border-info h-28"
            value={classesText}
            onChange={(e) => setClassesText(e.target.value)}
          />
        </Field>

        <div className="flex items-center gap-3 pt-2">
          <button
            onClick={save}
            disabled={saving}
            className="rounded-md bg-info px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {saving ? "guardando…" : "Guardar y recargar"}
          </button>
          {msg && <span className="text-xs text-mut">{msg}</span>}
        </div>
      </div>
      <p className="mt-4 font-mono text-[11px] text-dim">
        actualizado: {cfg.updated_at ?? "—"}
      </p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block font-mono text-[11px] text-dim">{label}</span>
      {children}
    </label>
  );
}
