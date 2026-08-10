import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, auth } from "../lib/api";
import { useBranding } from "../lib/branding";

const SSO_LABELS: Record<string, string> = {
  microsoft: "Entrar con Microsoft",
  google: "Entrar con Google",
};

export default function LoginPage() {
  const brand = useBranding();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // SSO callback: /login?token=<jwt>
  useEffect(() => {
    const token = params.get("token");
    if (token) {
      auth.set(token);
      navigate("/", { replace: true });
    }
  }, [params, navigate]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const resp = await api.login(email, password);
      auth.set(resp.access_token);
      navigate("/", { replace: true });
    } catch {
      setError("Credenciales inválidas");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid h-screen place-items-center bg-base">
      <form
        onSubmit={submit}
        className="w-full max-w-sm space-y-5 rounded-lg border border-line bg-panel p-8"
      >
        <div className="flex items-center gap-3">
          <img src={brand.logo_dark_url} alt={brand.app_name} className="h-10 w-10" />
          <div>
            <div className="font-display text-2xl font-semibold tracking-tight">
              {brand.app_name}
            </div>
            {brand.company_name && <div className="text-xs text-mut">{brand.company_name}</div>}
          </div>
        </div>

        {brand.sso_providers.length > 0 && (
          <div className="space-y-2">
            {brand.sso_providers.map((p) => (
              <a
                key={p}
                href={`/api/v1/auth/oidc/${p}/login`}
                className="block w-full rounded-md border border-line px-4 py-2.5 text-center text-sm text-ink transition-colors hover:bg-raised"
              >
                {SSO_LABELS[p] ?? `Entrar con ${p}`}
              </a>
            ))}
            <div className="flex items-center gap-3 text-[11px] text-dim">
              <span className="h-px flex-1 bg-line" /> o con cuenta local <span className="h-px flex-1 bg-line" />
            </div>
          </div>
        )}

        <div className="space-y-3">
          <input
            type="email"
            required
            autoFocus
            placeholder="correo"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-line bg-base px-3 py-2.5 text-sm"
          />
          <input
            type="password"
            required
            placeholder="contraseña"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-line bg-base px-3 py-2.5 text-sm"
          />
        </div>
        {error && <p className="font-mono text-xs text-crit">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-brand px-4 py-2.5 text-sm font-medium text-white transition-opacity disabled:opacity-50"
        >
          {busy ? "Ingresando…" : "Ingresar"}
        </button>
        {brand.support_url && (
          <a href={brand.support_url} className="block text-center text-xs text-mut hover:text-ink">
            soporte
          </a>
        )}
      </form>
    </div>
  );
}
