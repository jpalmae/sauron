import { Activity, Bell, Camera, Car, ChartColumn, LogOut, Map, ScrollText, Search, SlidersHorizontal, Users, Video, ChevronDown } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { auth } from "../lib/api";
import { useBranding } from "../lib/branding";

function Section({
  label,
  icon: Icon,
  color,
  children,
  defaultOpen = true,
}: {
  label: string;
  icon: typeof Car;
  color: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const location = useLocation();
  const isActive = children
    ? (Array.isArray(children) ? children : [children]).some((c: any) => {
        const to = c?.props?.to;
        return to && location.pathname.startsWith(to);
      })
    : false;
  const [open, setOpen] = useState(defaultOpen || isActive);

  return (
    <div>
      <button
        onClick={() => setOpen((o) => !o)}
        className={`flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-xs font-semibold tracking-wider transition-colors ${open ? "text-ink" : "text-mut hover:text-ink"}`}
      >
        <Icon size={14} className={color} strokeWidth={1.8} />
        {label}
        <ChevronDown size={12} className={`ml-auto transition-transform ${open ? "" : "-rotate-90"} text-dim`} />
      </button>
      {open && <div className="mt-0.5 flex flex-col gap-0.5 pl-2">{children}</div>}
    </div>
  );
}

function NavItem({ to, label, icon: Icon, end }: { to: string; label: string; icon: typeof Video; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-md px-3 py-1.5 text-sm transition-colors ${isActive ? "bg-raised text-ink" : "text-mut hover:bg-raised/60 hover:text-ink"}`
      }
    >
      <Icon size={15} strokeWidth={1.8} />
      {label}
    </NavLink>
  );
}

export default function Layout({ wsConnected }: { wsConnected: boolean }) {
  const brand = useBranding();
  const navigate = useNavigate();
  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-panel">
        <div className="flex items-center gap-3 px-5 py-5">
          <img src={brand.logo_dark_url} alt={brand.app_name} className="h-8 w-8" />
          <div className="leading-tight">
            <div className="font-display text-lg font-semibold tracking-tight">{brand.app_name}</div>
            {brand.company_name && <div className="text-[11px] text-mut">{brand.company_name}</div>}
          </div>
        </div>
        <nav className="mt-2 flex flex-col gap-1 px-2 overflow-y-auto">
          <NavItem to="/" label="Dashboard" icon={ChartColumn} end />
          <Section label="Tráfico" icon={Car} color="text-info" defaultOpen>
            <NavItem to="/traffic/live" label="En vivo" icon={Video} />
            <NavItem to="/traffic/analytics" label="Analítica" icon={ChartColumn} />
            <NavItem to="/traffic/events" label="Eventos" icon={ScrollText} />
          </Section>
          <Section label="Personas" icon={Users} color="text-warn" defaultOpen>
            <NavItem to="/people/live" label="En vivo" icon={Video} />
            <NavItem to="/people/analytics" label="Analítica" icon={ChartColumn} />
            <NavItem to="/people/events" label="Eventos" icon={ScrollText} />
          </Section>
          <div className="my-1 border-t border-line/60" />
          <NavItem to="/map" label="Mapa" icon={Map} />
          <NavItem to="/search" label="Búsqueda" icon={Search} />
          <NavItem to="/cameras" label="Cámaras" icon={Camera} />
          <NavItem to="/notifications" label="Notificaciones" icon={Bell} />
          <NavItem to="/engine" label="Engine" icon={SlidersHorizontal} />
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
