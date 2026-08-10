import { Activity, Camera, ChartColumn, LogOut, Map, ScrollText, Search, Video } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { auth } from "../lib/api";
import { useBranding } from "../lib/branding";

const NAV = [
  { to: "/", label: "En vivo", icon: Video, end: true },
  { to: "/analytics", label: "Analítica", icon: ChartColumn },
  { to: "/search", label: "Búsqueda", icon: Search },
  { to: "/map", label: "Mapa", icon: Map },
  { to: "/events", label: "Eventos", icon: ScrollText },
  { to: "/cameras", label: "Cámaras", icon: Camera },
];

export default function Layout({ wsConnected }: { wsConnected: boolean }) {
  const brand = useBranding();
  const navigate = useNavigate();
  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-panel">
        <div className="flex items-center gap-3 px-5 py-5">
          <img src={brand.logo_dark_url} alt={brand.app_name} className="h-8 w-8" />
          <div className="leading-tight">
            <div className="font-display text-lg font-semibold tracking-tight">
              {brand.app_name}
            </div>
            {brand.company_name && (
              <div className="text-[11px] text-mut">{brand.company_name}</div>
            )}
          </div>
        </div>
        <nav className="mt-2 flex flex-col gap-0.5 px-2">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? "bg-raised text-ink"
                    : "text-mut hover:bg-raised/60 hover:text-ink"
                }`
              }
            >
              <Icon size={16} strokeWidth={1.8} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-2 px-5 py-4">
          <div className="flex items-center gap-2 font-mono text-[11px] text-mut">
            <Activity size={12} className={wsConnected ? "text-info" : "text-crit"} />
            {wsConnected ? "alertas en línea" : "alertas desconectadas"}
          </div>
          {brand.auth_required && (
            <button
              onClick={() => {
                auth.clear();
                navigate("/login");
              }}
              className="flex items-center gap-2 font-mono text-[11px] text-dim transition-colors hover:text-ink"
            >
              <LogOut size={12} /> salir
            </button>
          )}
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
