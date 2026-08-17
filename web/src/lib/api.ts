export interface Branding {
  app_name: string;
  company_name: string;
  logo_light_url: string;
  logo_dark_url: string;
  favicon_url: string;
  primary_color: string;
  accent_color: string;
  support_url: string;
  auth_required: boolean;
  sso_providers: string[];
}

export interface Camera {
  id: string;
  name: string;
  stream_id: string;
  rtsp_url: string;
  roi_config: RoiConfig | null;
  is_active: boolean;
  latitude: number | null;
  longitude: number | null;
  analytics_profile: "traffic" | "people";
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
  acknowledged_at: string | null;
  acknowledged_by: string | null;
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

export interface OccupancyStats {
  timestamp: string | null;
  count: number | null;
  by_class: Record<string, number> | null;
  unique_total: number | null;
  avg_dwell_s: number | null;
  peak: number | null;
  peak_today: number | null;
  avg_last_hour: number | null;
  posture: { standing: number; sitting: number; fallen: number; unknown: number } | null;
  sit_to_stand: number | null;
  stand_to_sit: number | null;
  transitions: number | null;
  unique_reid: number | null;
  falls: number | null;
  seats: number | null;
  occupied_seats: number | null;
  free_seats: number | null;
  seat_utilization: number | null;
}

export interface DetectionObj {
  id: number;
  class: string;
  box: [number, number, number, number];
  posture?: string;
  vehicle_type?: string;
  keypoints?: [number, number][];
}

export interface DetectionsPayload {
  status: "live" | "stale";
  ts: number | null;
  width: number;
  height: number;
  objects: DetectionObj[];
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
  rules?: ("stopped" | "wrong_way" | "congestion" | "occupancy")[];
  direction?: [number, number] | null;
}

export interface EventFilters {
  camera_id?: string;
  event_type?: string;
  priority?: string;
  since?: string;
  until?: string;
  pending_only?: boolean;
}

const TOKEN_KEY = "sauron_token";

export const auth = {
  token: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

const BASE = import.meta.env.VITE_API_BASE ?? "";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = auth.token();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const resp = await fetch(`${BASE}${path}`, { headers, ...init });
  if (resp.status === 401 && !path.includes("/auth/login")) {
    auth.clear();
    if (location.pathname !== "/login") location.assign("/login");
    throw new Error("unauthorized");
  }
  if (!resp.ok) {
    const detail = await resp.text().catch(() => "");
    throw new Error(`API ${resp.status}: ${detail || resp.statusText}`);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  branding: () => apiFetch<Branding>("/api/v1/branding"),
  login: (email: string, password: string) =>
    apiFetch<{ access_token: string; email: string; role: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  cameras: () => apiFetch<Camera[]>("/api/v1/cameras"),
  createCamera: (c: Partial<Camera>) =>
    apiFetch<Camera>("/api/v1/cameras", { method: "POST", body: JSON.stringify(c) }),
  updateCamera: (id: string, patch: Partial<Camera>) =>
    apiFetch<Camera>(`/api/v1/cameras/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteCamera: (id: string) =>
    fetch(`${BASE}/api/v1/cameras/${id}`, {
      method: "DELETE",
      headers: auth.token() ? { Authorization: `Bearer ${auth.token()}` } : {},
    }).then((r) => {
      if (!r.ok) throw new Error(`API ${r.status}`);
    }),
  events: (filters: EventFilters = {}, page = 1, pageSize = 50) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== false) params.set(k, String(v));
    });
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    return apiFetch<EventPage>(`/api/v1/events?${params}`);
  },
  ackEvent: (eventId: string) =>
    apiFetch<EventItem>(`/api/v1/events/${eventId}/ack`, { method: "POST" }),
  setFeedback: (eventId: string, value: "correct" | "false_positive") =>
    fetch(`${BASE}/api/v1/events/${eventId}/feedback`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(auth.token() ? { Authorization: `Bearer ${auth.token()}` } : {}),
      },
      body: JSON.stringify({ value }),
    }).then((r) => {
      if (!r.ok) throw new Error(`API ${r.status}`);
    }),
  datasetUrl: (feedback: string, cameraId?: string) => {
    const params = new URLSearchParams({ feedback });
    if (cameraId) params.set("camera_id", cameraId);
    return `/api/v1/reports/dataset-coco.zip?${params}`;
  },
  liveUrl: (streamId: string) =>
    apiFetch<{ kind: "hls" | "whep" | "none"; url: string }>(
      `/api/v1/streams/${streamId}/live-url`,
    ),
  search: (q: string, cameraId?: string, limit = 24) => {
    const params = new URLSearchParams({ q, limit: String(limit) });
    if (cameraId) params.set("camera_id", cameraId);
    return apiFetch<{ query: string; results: { distance: number; event: EventItem }[] }>(
      `/api/v1/search?${params}`,
    );
  },
  pushPublicKey: () => apiFetch<{ public_key: string }>("/api/v1/push/public-key"),
  pushSubscribe: (endpoint: string, keys: { p256dh: string; auth: string }) =>
    apiFetch("/api/v1/push/subscribe", {
      method: "POST",
      body: JSON.stringify({ endpoint, keys }),
    }),
  synopsisUrl: (cameraId: string | null, hours: number, eventType?: string) => {
    const params = new URLSearchParams({ hours: String(hours) });
    if (cameraId) params.set("camera_id", cameraId);
    if (eventType) params.set("event_type", eventType);
    return `/api/v1/reports/synopsis.jpg?${params}`;
  },
  notificationChannels: () =>
    apiFetch<
      {
        id: string;
        name: string;
        type: string;
        config: Record<string, string>;
        min_priority: string;
        camera_id: string | null;
        enabled: boolean;
      }[]
    >("/api/v1/notifications"),
  createChannel: (c: Record<string, unknown>) =>
    apiFetch("/api/v1/notifications", { method: "POST", body: JSON.stringify(c) }),
  updateChannel: (id: string, patch: Record<string, unknown>) =>
    apiFetch(`/api/v1/notifications/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteChannel: (id: string) =>
    fetch(`${BASE}/api/v1/notifications/${id}`, {
      method: "DELETE",
      headers: auth.token() ? { Authorization: `Bearer ${auth.token()}` } : {},
    }).then((r) => {
      if (!r.ok) throw new Error(`API ${r.status}`);
    }),
  testChannel: (id: string) =>
    apiFetch(`/api/v1/notifications/${id}/test`, { method: "POST" }),
  occupancy: (cameraId: string) =>
    apiFetch<OccupancyStats>(`/api/v1/cameras/${cameraId}/occupancy`),
  detections: (cameraId: string) =>
    apiFetch<DetectionsPayload>(`/api/v1/cameras/${cameraId}/detections`),
  kpis: (cameraId: string | null, since: Date, until: Date, bucket: string) => {
    const params = new URLSearchParams({ bucket });
    if (cameraId) params.set("camera_id", cameraId);
    params.set("since", since.toISOString());
    params.set("until", until.toISOString());
    return apiFetch<KpiRow[]>(`/api/v1/kpis?${params}`);
  },
  eventsCsvUrl: (filters: EventFilters = {}) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== false) params.set(k, String(v));
    });
    return `${BASE}/api/v1/reports/events.csv?${params}`;
  },
  kpisCsvUrl: (bucket: string) => `${BASE}/api/v1/reports/kpis.csv?bucket=${bucket}`,
  /** CSV download with auth header (plain <a href> can't carry JWT). */
  download: async (path: string, filename: string) => {
    const headers: Record<string, string> = {};
    const token = auth.token();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const resp = await fetch(`${BASE}${path}`, { headers });
    if (!resp.ok) throw new Error(`API ${resp.status}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },
};
