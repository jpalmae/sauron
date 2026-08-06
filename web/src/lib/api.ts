export interface Branding {
  app_name: string;
  company_name: string;
  logo_light_url: string;
  logo_dark_url: string;
  favicon_url: string;
  primary_color: string;
  accent_color: string;
  support_url: string;
}

export interface Camera {
  id: string;
  name: string;
  stream_id: string;
  rtsp_url: string;
  roi_config: RoiConfig | null;
  is_active: boolean;
}

export interface EventItem {
  event_id: string;
  timestamp: string;
  camera_id: string;
  event_type: string;
  priority: "info" | "warning" | "critical";
  confidence: number | null;
  rule_id: string;
  object_id: number | null;
  metadata: Record<string, unknown> | null;
  snapshot_url: string | null;
  clip_url: string | null;
}

export interface EventPage {
  total: number;
  page: number;
  page_size: number;
  items: EventItem[];
}

export interface KpiRow {
  bucket: string;
  camera_id: string;
  vehicle_class: string | null;
  total_count: number;
  avg_speed_kmh: number | null;
  congestion_minutes: number;
}

export interface RoiConfig {
  lines?: RoiLine[];
  polygons?: RoiPolygon[];
  homography?: { src_points: [number, number][]; dst_points: [number, number][] } | null;
  thresholds?: Record<string, number>;
}

export interface RoiLine {
  id: string;
  points: [number, number][];
  direction?: [number, number] | null;
  classes?: string[] | null;
}

export interface RoiPolygon {
  id: string;
  points: [number, number][];
  kind?: "lane" | "parking" | "counting";
  rules?: ("stopped" | "wrong_way" | "congestion")[];
  direction?: [number, number] | null;
}

export interface EventFilters {
  camera_id?: string;
  event_type?: string;
  priority?: string;
  since?: string;
  until?: string;
}

const BASE = import.meta.env.VITE_API_BASE ?? "";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    const detail = await resp.text().catch(() => "");
    throw new Error(`API ${resp.status}: ${detail || resp.statusText}`);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  branding: () => apiFetch<Branding>("/api/v1/branding"),
  cameras: () => apiFetch<Camera[]>("/api/v1/cameras"),
  createCamera: (c: Partial<Camera>) =>
    apiFetch<Camera>("/api/v1/cameras", { method: "POST", body: JSON.stringify(c) }),
  updateCamera: (id: string, patch: Partial<Camera>) =>
    apiFetch<Camera>(`/api/v1/cameras/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteCamera: (id: string) =>
    fetch(`${BASE}/api/v1/cameras/${id}`, { method: "DELETE" }).then((r) => {
      if (!r.ok) throw new Error(`API ${r.status}`);
    }),
  events: (filters: EventFilters = {}, page = 1, pageSize = 50) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => v && params.set(k, v));
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    return apiFetch<EventPage>(`/api/v1/events?${params}`);
  },
  kpis: (cameraId: string | null, since: Date, until: Date, bucket: string) => {
    const params = new URLSearchParams({ bucket });
    if (cameraId) params.set("camera_id", cameraId);
    params.set("since", since.toISOString());
    params.set("until", until.toISOString());
    return apiFetch<KpiRow[]>(`/api/v1/kpis?${params}`);
  },
  eventsCsvUrl: (filters: EventFilters = {}) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => v && params.set(k, v));
    return `${BASE}/api/v1/reports/events.csv?${params}`;
  },
  kpisCsvUrl: (bucket: string) => `${BASE}/api/v1/reports/kpis.csv?bucket=${bucket}`,
};
