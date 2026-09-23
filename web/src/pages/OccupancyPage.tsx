import { CameraOff } from "lucide-react";
import { useEffect, useState } from "react";
import OccupancyWidget from "../components/OccupancyWidget";
import { api, type Camera } from "../lib/api";
import { filterCamerasByDomain } from "../lib/domain";

export default function OccupancyPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [states, setStates] = useState<Record<string, boolean>>({});

  useEffect(() => {
    api.cameras().then(setCameras).catch(console.error);
  }, []);

  const onStateChange = (id: string, ok: boolean) =>
    setStates((prev) => (prev[id] === ok ? prev : { ...prev, [id]: ok }));

  const cams = filterCamerasByDomain(cameras, "people");
  // mismo criterio que En vivo: sin datos al fondo y compactas
  const online = cams.filter((c) => states[c.id] !== false);
  const offline = cams.filter((c) => states[c.id] === false);

  return (
    <div className="h-full overflow-y-auto p-4">
      <h1 className="mb-1 font-display text-lg font-semibold">Ocupación por cámara</h1>
      <p className="mb-4 text-sm text-dim">
        Personas presentes, postura, picos del día y permanencia — actualiza cada 10 s.
      </p>
      {cams.length === 0 && (
        <p className="text-sm text-dim">
          Sin cámaras de personas configuradas.{" "}
          <span className="text-mut">Añádelas en Cámaras.</span>
        </p>
      )}
      <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
        {online.map((c) => (
          <OccupancyWidget key={c.id} cameraId={c.id} name={c.name} onStateChange={onStateChange} />
        ))}
      </div>
      {offline.length > 0 && (
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {offline.map((c) => (
            <div
              key={c.id}
              className="flex items-center gap-2 rounded-lg border border-line/60 bg-panel/60 px-3 py-2.5"
              role="status"
            >
              <CameraOff size={14} className="shrink-0 text-crit" strokeWidth={1.5} />
              <span className="truncate font-display text-xs text-mut">{c.name}</span>
              <span className="ml-auto shrink-0 font-mono text-[10px] text-crit">sin datos</span>
              {/* el widget sigue montado oculto: al recuperar datos vuelve solo arriba */}
              <div className="hidden">
                <OccupancyWidget cameraId={c.id} name={c.name} onStateChange={onStateChange} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
