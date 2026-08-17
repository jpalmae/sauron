import { Download } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type Camera, type KpiRow } from "../lib/api";
import { DOMAIN_LABEL, filterCamerasByDomain } from "../lib/domain";
import { CLASS_LABELS } from "../lib/format";
import { congestionSeries, pivotCounts, speedSeries } from "../lib/kpis";
import OccupancyWidget from "../components/OccupancyWidget";

const CLASS_COLORS: Record<string, string> = {
  car: "oklch(0.78 0.13 165)",
  bus: "oklch(0.82 0.14 85)",
  truck: "oklch(0.70 0.15 250)",
  motorcycle: "oklch(0.66 0.21 27)",
};

const RANGES = [
  { label: "24 h", hours: 24, bucket: "hour" },
  { label: "7 días", hours: 24 * 7, bucket: "day" },
  { label: "30 días", hours: 24 * 30, bucket: "day" },
] as const;

const tooltipStyle = {
  backgroundColor: "var(--color-raised)",
  border: "1px solid var(--color-line)",
  borderRadius: 8,
  fontSize: 12,
};

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-4">
      <h3 className="mb-3 font-display text-sm font-semibold tracking-wide text-mut">
        {title}
      </h3>
      <div className="h-64">{children}</div>
    </section>
  );
}

export default function AnalyticsPage({ domain }: { domain?: "traffic" | "people" } = {}) {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<string | null>(null);
  const [rangeIdx, setRangeIdx] = useState(0);
  const [rows, setRows] = useState<KpiRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const isPeople = domain === "people";

  const range = RANGES[rangeIdx];

  useEffect(() => {
    api.cameras().then(setCameras).catch(console.error);
  }, []);

  useEffect(() => {
    if (isPeople) return;
    const until = new Date();
    const since = new Date(until.getTime() - range.hours * 3600_000);
    setError(null);
    api
      .kpis(cameraId, since, until, range.bucket)
      .then(setRows)
      .catch((e) => {
        setRows([]);
        setError(String(e));
      });
  }, [cameraId, range, isPeople]);

  const counts = useMemo(() => pivotCounts(rows, range.bucket), [rows, range.bucket]);
  const speeds = useMemo(() => speedSeries(rows, range.bucket), [rows, range.bucket]);
  const congestion = useMemo(() => congestionSeries(rows, range.bucket), [rows, range.bucket]);
  const filteredCameras = useMemo(() => (domain ? filterCamerasByDomain(cameras, domain) : cameras), [cameras, domain]);

  if (isPeople) {
    return (
      <div className="space-y-4 p-5">
        <h1 className="font-display text-xl font-semibold">Analítica de personas</h1>
        {filteredCameras.length === 0 ? (
          <p className="text-sm text-dim">
            Sin cámaras de personas configuradas. Asigna el perfil Personas en <span className="text-mut">Cámaras</span>.
          </p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {filteredCameras.map((c) => (
              <OccupancyWidget key={c.id} cameraId={c.id} name={c.name} />
            ))}
          </div>
        )}
        <p className="text-xs text-dim">
          La ocupación se calcula con detección de personas y seguimiento NvDCF. Usa <span className="font-mono text-mut">Eventos · Personas</span> para el histórico.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-display text-xl font-semibold">Analítica de tráfico</h1>
        <div className="ml-auto flex items-center gap-2">
          <select
            value={cameraId ?? ""}
            onChange={(e) => setCameraId(e.target.value || null)}
            className="rounded-md border border-line bg-panel px-3 py-1.5 text-sm"
          >
            <option value="">{domain ? `Todas (${DOMAIN_LABEL[domain!]})` : "Todas las cámaras"}</option>
            {(domain ? filteredCameras : cameras).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <div className="flex overflow-hidden rounded-md border border-line">
            {RANGES.map((r, i) => (
              <button
                key={r.label}
                onClick={() => setRangeIdx(i)}
                className={`px-3 py-1.5 text-sm transition-colors ${
                  i === rangeIdx ? "bg-raised text-ink" : "text-mut hover:text-ink"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => void api.download(`/api/v1/reports/kpis.csv?bucket=${range.bucket}`, "kpis.csv")}
            className="flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm text-mut transition-colors hover:text-ink"
          >
            <Download size={14} /> CSV
          </button>
        </div>
      </div>

      {error && (
        <p className="rounded-md border border-crit/40 bg-crit/10 px-4 py-2 font-mono text-xs text-crit">
          {error}
        </p>
      )}

      <ChartCard title="CONTEO POR CLASE">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={counts}>
            <CartesianGrid stroke="var(--color-line)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" tick={{ fill: "var(--color-mut)", fontSize: 11 }} />
            <YAxis tick={{ fill: "var(--color-mut)", fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {(["car", "bus", "truck", "motorcycle"] as const).map((cls) => (
              <Bar
                key={cls}
                dataKey={cls}
                name={CLASS_LABELS[cls]}
                stackId="a"
                fill={CLASS_COLORS[cls]}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartCard title="VELOCIDAD PROMEDIO (km/h)">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={speeds}>
              <CartesianGrid stroke="var(--color-line)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "var(--color-mut)", fontSize: 11 }} />
              <YAxis tick={{ fill: "var(--color-mut)", fontSize: 11 }} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line
                type="monotone"
                dataKey="avg_speed_kmh"
                name="km/h"
                stroke="var(--color-brand)"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="CONGESTIÓN (minutos)">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={congestion}>
              <CartesianGrid stroke="var(--color-line)" strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "var(--color-mut)", fontSize: 11 }} />
              <YAxis tick={{ fill: "var(--color-mut)", fontSize: 11 }} />
              <Tooltip contentStyle={tooltipStyle} />
              <Area
                type="monotone"
                dataKey="minutes"
                name="min"
                stroke="var(--color-warn)"
                fill="var(--color-warn)"
                fillOpacity={0.15}
              />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
}
