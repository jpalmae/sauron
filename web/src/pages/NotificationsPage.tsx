import { Bell, CalendarClock, Plus, Send, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

interface Channel {
  id: string;
  name: string;
  type: string;
  config: Record<string, string>;
  min_priority: string;
  camera_id: string | null;
  enabled: boolean;
  cooldown_seconds: number;
  max_attempts: number;
}

interface Schedule {
  id: string;
  name: string;
  channel_id: string;
  frequency: "daily" | "weekly" | "monthly";
  hour: number;
  minute: number;
  timezone: string;
  enabled: boolean;
  next_run_at: string;
}

const EMPTY = {
  name: "", type: "webhook", url: "", bot_token: "", chat_id: "", min_priority: "critical",
  cooldown_seconds: 60, max_attempts: 5, smtp_host: "", smtp_port: 587, username: "", password: "", to_addrs: "",
};
const EMPTY_SCHEDULE = { name: "", channel_id: "", frequency: "daily", hour: 8, minute: 0, timezone: "America/Santiago" };

export default function NotificationsPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState(EMPTY);
  const [message, setMessage] = useState<string | null>(null);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [deliveries, setDeliveries] = useState<{ status: string; attempts: number; last_error: string | null }[]>([]);
  const [creatingSchedule, setCreatingSchedule] = useState(false);
  const [scheduleDraft, setScheduleDraft] = useState(EMPTY_SCHEDULE);

  const reload = () => Promise.all([
    api.notificationChannels().then(setChannels),
    api.reportSchedules().then(setSchedules),
    api.notificationDeliveries().then(setDeliveries),
  ]).catch(console.error);
  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => void reload(), 15_000);
    return () => window.clearInterval(timer);
  }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    const config =
      draft.type === "webhook"
        ? { url: draft.url }
        : draft.type === "telegram"
          ? { bot_token: draft.bot_token, chat_id: draft.chat_id }
          : {
              smtp_host: draft.smtp_host,
              smtp_port: draft.smtp_port,
              username: draft.username,
              password: draft.password,
              to_addrs: draft.to_addrs,
              start_tls: true,
            };
    await api.createChannel({
      name: draft.name,
      type: draft.type,
      config,
      min_priority: draft.min_priority,
      cooldown_seconds: draft.cooldown_seconds,
      max_attempts: draft.max_attempts,
    });
    setCreating(false);
    setDraft(EMPTY);
    await reload();
  };

  return (
    <div className="space-y-4 p-5">
      <div className="flex items-center gap-3">
        <h1 className="font-display text-xl font-semibold">Notificaciones</h1>
        <div className="flex gap-2 font-mono text-[10px] text-mut">
          <span className="rounded border border-line px-2 py-1">enviadas {deliveries.filter((d) => d.status === "sent").length}</span>
          <span className="rounded border border-line px-2 py-1">pendientes {deliveries.filter((d) => ["pending", "retry"].includes(d.status)).length}</span>
          <span className={`rounded border px-2 py-1 ${deliveries.some((d) => d.status === "failed") ? "border-crit/40 text-crit" : "border-line"}`}>fallidas {deliveries.filter((d) => d.status === "failed").length}</span>
        </div>
        <button
          onClick={() => {
            setScheduleDraft({ ...EMPTY_SCHEDULE, channel_id: channels[0]?.id ?? "" });
            setCreatingSchedule(true);
          }}
          disabled={channels.length === 0}
          className="ml-auto flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm text-mut hover:text-ink disabled:opacity-40"
        >
          <CalendarClock size={14} /> Programar reporte
        </button>
        <button
          onClick={() => setCreating(true)}
          className="flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white"
        >
          <Plus size={14} /> Nuevo canal
        </button>
      </div>

      {message && (
        <p className="rounded-md border border-line bg-panel px-4 py-2 font-mono text-xs text-mut">
          {message}
        </p>
      )}

      {creatingSchedule && (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            await api.createReportSchedule(scheduleDraft);
            setCreatingSchedule(false);
            await reload();
          }}
          className="grid gap-3 rounded-lg border border-line bg-panel p-4 md:grid-cols-6"
        >
          <input required placeholder="Nombre del reporte" value={scheduleDraft.name} onChange={(e) => setScheduleDraft({ ...scheduleDraft, name: e.target.value })} className="rounded-md border border-line bg-base px-3 py-2 text-sm md:col-span-2" />
          <select required value={scheduleDraft.channel_id} onChange={(e) => setScheduleDraft({ ...scheduleDraft, channel_id: e.target.value })} className="rounded-md border border-line bg-base px-3 py-2 text-sm">
            {channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.name}</option>)}
          </select>
          <select value={scheduleDraft.frequency} onChange={(e) => setScheduleDraft({ ...scheduleDraft, frequency: e.target.value })} className="rounded-md border border-line bg-base px-3 py-2 text-sm">
            <option value="daily">Diario</option><option value="weekly">Semanal</option><option value="monthly">Mensual</option>
          </select>
          <div className="flex items-center gap-1">
            <input type="number" min={0} max={23} value={scheduleDraft.hour} onChange={(e) => setScheduleDraft({ ...scheduleDraft, hour: Number(e.target.value) })} className="w-16 rounded-md border border-line bg-base px-2 py-2 font-mono text-sm" />:
            <input type="number" min={0} max={59} value={scheduleDraft.minute} onChange={(e) => setScheduleDraft({ ...scheduleDraft, minute: Number(e.target.value) })} className="w-16 rounded-md border border-line bg-base px-2 py-2 font-mono text-sm" />
          </div>
          <div className="flex gap-2">
            <button type="submit" className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white">Guardar</button>
            <button type="button" onClick={() => setCreatingSchedule(false)} className="rounded-md border border-line px-3 py-2 text-sm text-mut">Cancelar</button>
          </div>
        </form>
      )}

      {schedules.length > 0 && (
        <div className="rounded-lg border border-line bg-panel p-4">
          <h2 className="mb-3 font-display text-sm font-semibold">REPORTES PROGRAMADOS</h2>
          <div className="space-y-2">
            {schedules.map((schedule) => (
              <div key={schedule.id} className="flex items-center gap-3 rounded-md border border-line bg-base px-3 py-2 text-sm">
                <CalendarClock size={14} className="text-brand" />
                <span className="font-medium">{schedule.name}</span>
                <span className="font-mono text-xs text-mut">{schedule.frequency} · {String(schedule.hour).padStart(2, "0")}:{String(schedule.minute).padStart(2, "0")}</span>
                <span className="ml-auto font-mono text-[10px] text-dim">próximo {new Date(schedule.next_run_at).toLocaleString()}</span>
                <button onClick={async () => { await api.updateReportSchedule(schedule.id, { enabled: !schedule.enabled }); await reload(); }} className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${schedule.enabled ? "border-info/40 text-info" : "border-line text-dim"}`}>{schedule.enabled ? "activo" : "pausado"}</button>
                <button title="Eliminar" onClick={async () => { await api.deleteReportSchedule(schedule.id); await reload(); }} className="rounded p-1 text-mut hover:text-crit"><Trash2 size={13} /></button>
              </div>
            ))}
          </div>
        </div>
      )}

      {creating && (
        <form onSubmit={create} className="space-y-3 rounded-lg border border-line bg-panel p-4">
          <div className="flex gap-2">
            <input
              required
              placeholder="Nombre (p. ej. Ops Telegram)"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              className="flex-1 rounded-md border border-line bg-base px-3 py-2 text-sm"
            />
            <select
              value={draft.type}
              onChange={(e) => setDraft({ ...draft, type: e.target.value })}
              className="rounded-md border border-line bg-base px-3 py-2 text-sm"
            >
              <option value="webhook">Webhook</option>
              <option value="telegram">Telegram</option>
              <option value="email">Email SMTP</option>
            </select>
            <select
              value={draft.min_priority}
              onChange={(e) => setDraft({ ...draft, min_priority: e.target.value })}
              className="rounded-md border border-line bg-base px-3 py-2 text-sm"
              title="Prioridad mínima"
            >
              <option value="info">info+</option>
              <option value="warning">warning+</option>
              <option value="critical">solo critical</option>
            </select>
          </div>
          {draft.type === "webhook" ? (
            <input
              required
              placeholder="https://hooks.slack.com/… o URL genérica"
              value={draft.url}
              onChange={(e) => setDraft({ ...draft, url: e.target.value })}
              className="w-full rounded-md border border-line bg-base px-3 py-2 font-mono text-sm"
            />
          ) : draft.type === "telegram" ? (
            <div className="flex gap-2">
              <input
                required
                placeholder="bot_token (de @BotFather)"
                value={draft.bot_token}
                onChange={(e) => setDraft({ ...draft, bot_token: e.target.value })}
                className="flex-1 rounded-md border border-line bg-base px-3 py-2 font-mono text-sm"
              />
              <input
                required
                placeholder="chat_id"
                value={draft.chat_id}
                onChange={(e) => setDraft({ ...draft, chat_id: e.target.value })}
                className="w-40 rounded-md border border-line bg-base px-3 py-2 font-mono text-sm"
              />
            </div>
          ) : (
            <div className="grid gap-2 md:grid-cols-3">
              <input required placeholder="Servidor SMTP" value={draft.smtp_host} onChange={(e) => setDraft({ ...draft, smtp_host: e.target.value })} className="rounded-md border border-line bg-base px-3 py-2 font-mono text-sm" />
              <input required type="number" placeholder="Puerto" value={draft.smtp_port} onChange={(e) => setDraft({ ...draft, smtp_port: Number(e.target.value) })} className="rounded-md border border-line bg-base px-3 py-2 font-mono text-sm" />
              <input required placeholder="Destinatarios separados por coma" value={draft.to_addrs} onChange={(e) => setDraft({ ...draft, to_addrs: e.target.value })} className="rounded-md border border-line bg-base px-3 py-2 text-sm" />
              <input required placeholder="Usuario o remitente SMTP" value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })} className="rounded-md border border-line bg-base px-3 py-2 text-sm" />
              <input type="password" placeholder="Contraseña SMTP" value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} className="rounded-md border border-line bg-base px-3 py-2 text-sm" />
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3 text-xs text-mut">
            <label className="flex items-center gap-2">Cooldown
              <input type="number" min={0} max={86400} value={draft.cooldown_seconds} onChange={(e) => setDraft({ ...draft, cooldown_seconds: Number(e.target.value) })} className="w-24 rounded border border-line bg-base px-2 py-1 font-mono" /> segundos
            </label>
            <label className="flex items-center gap-2">Intentos máximos
              <input type="number" min={1} max={20} value={draft.max_attempts} onChange={(e) => setDraft({ ...draft, max_attempts: Number(e.target.value) })} className="w-16 rounded border border-line bg-base px-2 py-1 font-mono" />
            </label>
          </div>
          <div className="flex gap-2">
            <button type="submit" className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white">
              Guardar
            </button>
            <button
              type="button"
              onClick={() => setCreating(false)}
              className="rounded-md border border-line px-4 py-2 text-sm text-mut hover:text-ink"
            >
              Cancelar
            </button>
          </div>
        </form>
      )}

      <div className="overflow-hidden rounded-lg border border-line">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line bg-panel text-left font-mono text-[11px] uppercase tracking-wider text-mut">
              <th className="px-4 py-2.5">Canal</th>
              <th className="px-4 py-2.5">Tipo</th>
              <th className="px-4 py-2.5">Prioridad mín.</th>
              <th className="px-4 py-2.5">Entrega</th>
              <th className="px-4 py-2.5">Estado</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {channels.map((ch) => (
              <tr key={ch.id} className="border-b border-line/50">
                <td className="px-4 py-2.5 font-medium">
                  <span className="mr-2 inline-block align-middle"><Bell size={13} /></span>
                  {ch.name}
                </td>
                <td className="px-4 py-2.5 font-mono text-xs text-mut">{ch.type}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-mut">{ch.min_priority}+</td>
                <td className="px-4 py-2.5 font-mono text-xs text-mut">{ch.cooldown_seconds}s · {ch.max_attempts} intentos</td>
                <td className="px-4 py-2.5">
                  <button
                    onClick={async () => {
                      await api.updateChannel(ch.id, { enabled: !ch.enabled });
                      await reload();
                    }}
                    className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${
                      ch.enabled ? "border-info/40 bg-info/10 text-info" : "border-line text-dim"
                    }`}
                  >
                    {ch.enabled ? "activo" : "pausado"}
                  </button>
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center justify-end gap-1">
                    <button
                      title="Enviar prueba"
                      onClick={async () => {
                        setMessage(`enviando prueba a ${ch.name}…`);
                        try {
                          await api.testChannel(ch.id);
                          setMessage(`prueba enviada a ${ch.name} ✓`);
                        } catch (e) {
                          setMessage(`falló la prueba: ${e}`);
                        }
                      }}
                      className="rounded p-1.5 text-mut hover:bg-raised hover:text-ink"
                    >
                      <Send size={14} />
                    </button>
                    <button
                      title="Eliminar"
                      onClick={async () => {
                        await api.deleteChannel(ch.id);
                        await reload();
                      }}
                      className="rounded p-1.5 text-mut hover:bg-raised hover:text-crit"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {channels.length === 0 && (
          <p className="px-4 py-10 text-center text-sm text-mut">
            Sin canales. Crea uno para recibir alertas por webhook, Telegram o email.
          </p>
        )}
      </div>
    </div>
  );
}
