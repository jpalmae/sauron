import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, auth } from "../lib/api";
import { useBranding } from "../lib/branding";

export default function LoginPage() {
  const brand = useBranding();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
