import { useEffect, useState } from "react";
import OccupancyWidget from "../components/OccupancyWidget";
import { api, type Camera } from "../lib/api";
import { filterCamerasByDomain } from "../lib/domain";

export default function OccupancyPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);

  useEffect(() => {
    api.cameras().then(setCameras).catch(console.error);
  }, []);

  const cams = filterCamerasByDomain(cameras, "people");

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
        {cams.map((c) => (
          <OccupancyWidget key={c.id} cameraId={c.id} name={c.name} />
        ))}
      </div>
    </div>
  );
}
