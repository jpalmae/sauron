import { useEffect, useState } from "react";
import { Activity, Armchair, Clock, Hash, TrendingUp, Users } from "lucide-react";
import { api, type OccupancyStats } from "../lib/api";

export default function OccupancyWidget({
  cameraId,
  name,
}: {
  cameraId: string;
  name: string;
}) {
  const [s, setS] = useState<OccupancyStats | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .occupancy(cameraId)
        .then((d) => alive && setS(d))
        .catch(() => {});
    load();
    const t = setInterval(load, 10_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [cameraId]);

  const rows: { icon: typeof Users; label: string; value: string | number }[][] = [
    [
      { icon: Users, label: "Ahora", value: s?.count ?? "—" },
      { icon: TrendingUp, label: "Pico hoy", value: s?.peak_today ?? s?.peak ?? "—" },
      { icon: Hash, label: "Únicos", value: s?.unique_reid ?? s?.unique_total ?? "—" },
      { icon: Clock, label: "Permanencia", value: s?.avg_dwell_s != null ? `${s.avg_dwell_s}s` : "—" },
    ],
    [
      { icon: Users, label: "De pie", value: s?.posture?.standing ?? "—" },
      { icon: Armchair, label: "Sentados", value: s?.posture?.sitting ?? "—" },
      { icon: Activity, label: "Se pararon", value: s?.sit_to_stand ?? "—" },
      { icon: Activity, label: "Cambios", value: s?.transitions ?? "—" },
    ],
    [
      { icon: Armchair, label: "Sillas", value: s?.seats ?? "—" },
      { icon: Armchair, label: "Ocupadas", value: s?.occupied_seats ?? "—" },
      { icon: Armchair, label: "Libres", value: s?.free_seats ?? "—" },
      { icon: Activity, label: "Caídas", value: s?.falls ?? "—" },
    ],
  ];

  return (
    <div className="rounded-lg border border-line bg-panel p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-display text-xs font-medium text-mut">{name}</span>
        <span className="font-mono text-[10px] text-dim">ocupación · postura · sillas</span>
      </div>
      <div className="flex flex-col gap-2">
        {rows.map((cells, ri) => (
          <div key={ri} className="grid grid-cols-4 gap-2">
            {cells.map((c) => (
              <div
                key={c.label}
                className="flex flex-col items-center gap-1 rounded-md bg-base/60 px-2 py-2"
              >
                <c.icon size={15} className="text-info" />
                <span className="font-display text-lg font-semibold leading-none text-ink">
                  {c.value}
                </span>
                <span className="font-mono text-[9px] text-dim">{c.label}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
