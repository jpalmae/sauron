import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { ExternalLink } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { MapContainer, Marker, Popup, TileLayer } from "react-leaflet";
import { Link } from "react-router-dom";
import { api, type Camera, type EventItem } from "../lib/api";
import { EVENT_LABELS, SEVERITY_DOT, relTime } from "../lib/format";

function markerIcon(color: string): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid rgba(255,255,255,.85);box-shadow:0 0 6px rgba(0,0,0,.6)"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

const COLOR = { ok: "#34d399", warn: "#fbbf24", crit: "#f87171" };

export default function MapPage() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [latest, setLatest] = useState<Record<string, EventItem>>({});

  useEffect(() => {
    api.cameras().then(setCameras).catch(console.error);
    api
      .events({}, 1, 50)
      .then((page) => {
        const map: Record<string, EventItem> = {};
        for (const e of page.items) {
          if (!map[e.camera_id]) map[e.camera_id] = e;
        }
        setLatest(map);
      })
      .catch(console.error);
  }, []);

  const located = cameras.filter((c) => c.latitude !== null && c.longitude !== null);
  const center = useMemo<[number, number]>(() => {
    if (located.length === 0) return [0, 0];
    const lat = located.reduce((s, c) => s + (c.latitude ?? 0), 0) / located.length;
    const lon = located.reduce((s, c) => s + (c.longitude ?? 0), 0) / located.length;
    return [lat, lon];
  }, [located]);

  return (
    <div className="flex h-full flex-col p-5">
      <div className="mb-3 flex items-baseline gap-3">
        <h1 className="font-display text-xl font-semibold">Mapa</h1>
        <span className="font-mono text-xs text-mut">
          {located.length}/{cameras.length} cámaras georreferenciadas
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-hidden rounded-lg border border-line">
        {located.length === 0 ? (
          <div className="grid h-full place-items-center text-sm text-mut">
            <p className="max-w-sm text-center">
              Asigna latitud/longitud a tus cámaras (Cámaras → editar) para verlas en el mapa.
            </p>
          </div>
        ) : (
          <MapContainer center={center} zoom={12} className="h-full w-full" style={{ background: "var(--color-base)" }}>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {located.map((cam) => {
              const last = latest[cam.id];
              const color =
                last?.priority === "critical"
                  ? COLOR.crit
                  : last?.priority === "warning"
                    ? COLOR.warn
                    : COLOR.ok;
              return (
                <Marker
                  key={cam.id}
                  position={[cam.latitude!, cam.longitude!]}
                  icon={markerIcon(color)}
                >
                  <Popup>
                    <div style={{ minWidth: 180 }}>
                      <strong>{cam.name}</strong>
                      <div style={{ fontSize: 12, opacity: 0.75, marginTop: 4 }}>
                        {cam.stream_id} · {cam.is_active ? "activa" : "inactiva"}
                        {cam.model && ` · ${cam.model}`}
                      </div>
                      {last && (
                        <div style={{ fontSize: 12, marginTop: 4 }}>
                          último: {EVENT_LABELS[last.event_type] ?? last.event_type}{" "}
                          {relTime(last.timestamp)}
                        </div>
                      )}
                      <div style={{ marginTop: 6, fontSize: 12 }}>
                        <Link to="/">en vivo ↗</Link> · <Link to={`/cameras/${cam.id}/roi`}>ROI ↗</Link>
                      </div>
                    </div>
                  </Popup>
                </Marker>
              );
            })}
          </MapContainer>
        )}
      </div>
      <div className="mt-2 flex gap-4 font-mono text-[11px] text-mut">
        <span className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${SEVERITY_DOT.info}`} /> sin alertas recientes</span>
        <span className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${SEVERITY_DOT.warning}`} /> warning reciente</span>
        <span className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${SEVERITY_DOT.critical}`} /> critical reciente</span>
        <ExternalLink size={11} className="ml-auto" />
      </div>
    </div>
  );
}
