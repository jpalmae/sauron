import { Car, Users, Video, ArrowRight, Map, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Camera, type EventItem } from "../lib/api";
import { filterCamerasByDomain, filterEventsByDomain, DOMAIN_LABEL } from "../lib/domain";

function StatCard({ title, icon: Icon, color, children, to }: { title: string; icon: typeof Car; color: string; children: React.ReactNode; to: string }) {
  return (
    <Link to={to} className="group rounded-lg border border-line bg-panel p-4 hover:border-brand/40 transition-colors">
      <div className="flex items-center gap-2">
        <Icon size={16} className={color} />
        <span className="font-display text-sm font-semibold tracking-wide">{title}</span>
        <ArrowRight size={12} className="ml-auto text-dim group-hover:text-ink transition-colors" />
      </div>
      <div className="mt-3">{children}</div>
    </Link>
  );
}

export default function Dashboard() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [events, setEvents] = useState<EventItem[]>([]);

  useEffect(() => {
    api.cameras().then(setCameras).catch(() => {});
    api.events({}, 1, 20).then((p) => setEvents(p.items)).catch(() => {});
  }, []);

  const trafficCams = filterCamerasByDomain(cameras, "traffic");
  const peopleCams = filterCamerasByDomain(cameras, "people");
  const trafficEvents = filterEventsByDomain(events, "traffic").slice(0, 3);
  const peopleEvents = filterEventsByDomain(events, "people").slice(0, 3);

  return (
    <div className="space-y-5 p-5">
      <div>
        <h1 className="font-display text-xl font-semibold">Dashboard</h1>
        <p className="text-sm text-mut">Resumen por dominio — cada sección tiene su En vivo, Analítica y Eventos.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <StatCard title={DOMAIN_LABEL.traffic} icon={Car} color="text-info" to="/traffic/live">
          <div className="flex items-baseline gap-3">
            <span className="font-display text-2xl font-semibold">{trafficCams.length}</span>
            <span className="text-xs text-mut">cámaras</span>
            <span className="ml-3 font-mono text-xs text-mut">{trafficEvents.length} eventos recientes</span>
          </div>
          <div className="mt-3 space-y-1">
            {trafficEvents.length === 0 ? (
              <p className="text-xs text-dim">Sin eventos recientes. Configura una ROI de tráfico para empezar.</p>
            ) : (
              trafficEvents.map((e) => (
                <div key={e.event_id} className="flex items-center gap-2 font-mono text-[11px] text-mut">
                  <span className="h-1.5 w-1.5 rounded-full bg-info" />
                  {e.event_type} · {e.priority}
                </div>
              ))
            )}
          </div>
          <div className="mt-3 flex gap-2">
            <Link to="/traffic/live" className="text-xs text-info hover:underline flex items-center gap-1">
              <Video size={12} /> En vivo
            </Link>
            <Link to="/traffic/analytics" className="text-xs text-info hover:underline">
              Analítica
            </Link>
          </div>
        </StatCard>

        <StatCard title={DOMAIN_LABEL.people} icon={Users} color="text-warn" to="/people/live">
          <div className="flex items-baseline gap-3">
            <span className="font-display text-2xl font-semibold">{peopleCams.length}</span>
            <span className="text-xs text-mut">cámaras</span>
            <span className="ml-3 font-mono text-xs text-mut">{peopleEvents.length} eventos recientes</span>
          </div>
          <div className="mt-3 space-y-1">
            {peopleEvents.length === 0 ? (
              <p className="text-xs text-dim">Sin eventos recientes. Activa pose/chair en una cámara de personas.</p>
            ) : (
              peopleEvents.map((e) => (
                <div key={e.event_id} className="flex items-center gap-2 font-mono text-[11px] text-mut">
                  <span className="h-1.5 w-1.5 rounded-full bg-warn" />
                  {e.event_type} · {e.priority}
                </div>
              ))
            )}
          </div>
          <div className="mt-3 flex gap-2">
            <Link to="/people/live" className="text-xs text-warn hover:underline flex items-center gap-1">
              <Video size={12} /> En vivo
            </Link>
            <Link to="/people/analytics" className="text-xs text-warn hover:underline">
              Analítica
            </Link>
          </div>
        </StatCard>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Link to="/map" className="rounded-lg border border-line bg-panel p-4 hover:border-brand/40 flex items-center gap-3">
          <Map size={16} className="text-mut" />
          <span className="text-sm">Mapa</span>
          <span className="ml-auto text-xs text-dim">{cameras.length} cámaras</span>
        </Link>
        <Link to="/search" className="rounded-lg border border-line bg-panel p-4 hover:border-brand/40 flex items-center gap-3">
          <Search size={16} className="text-mut" />
          <span className="text-sm">Búsqueda semántica</span>
        </Link>
        <div className="rounded-lg border border-line bg-panel p-4">
          <div className="text-sm font-medium">Estado global</div>
          <div className="mt-2 font-mono text-xs text-mut">{cameras.filter((c) => c.is_active).length} activas / {cameras.length} totales</div>
        </div>
      </div>
    </div>
  );
}
