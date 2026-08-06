import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Branding } from "./api";

const BrandingContext = createContext<Branding | null>(null);

export function useBranding(): Branding {
  const b = useContext(BrandingContext);
  if (!b) throw new Error("useBranding outside provider");
  return b;
}

function applyBranding(b: Branding) {
  document.title = b.app_name;
  const favicon = document.querySelector<HTMLLinkElement>("link[rel='icon']");
  if (favicon) favicon.href = b.favicon_url;
  const root = document.documentElement;
  root.style.setProperty("--brand-primary", b.primary_color);
  root.style.setProperty("--brand-accent", b.accent_color);
}

export function BrandingProvider({ children }: { children: ReactNode }) {
  const [branding, setBranding] = useState<Branding | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .branding()
      .then((b) => {
        applyBranding(b);
        setBranding(b);
      })
      .catch((e) => setError(String(e)));
  }, []);

  if (error) {
    return (
      <div className="grid h-screen place-items-center bg-base">
        <p className="font-mono text-sm text-crit">API no disponible — {error}</p>
      </div>
    );
  }
  if (!branding) {
    return (
      <div className="grid h-screen place-items-center bg-base">
        <div className="h-8 w-8 animate-pulse rounded-full border-2 border-brand" />
      </div>
    );
  }
  return <BrandingContext.Provider value={branding}>{children}</BrandingContext.Provider>;
}
