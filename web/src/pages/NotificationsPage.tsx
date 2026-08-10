import { Bell, Plus, Send, Trash2 } from "lucide-react";
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
}

const EMPTY = { name: "", type: "webhook", url: "", bot_token: "", chat_id: "", min_priority: "critical" };

export default function NotificationsPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState(EMPTY);
  const [message, setMessage] = useState<string | null>(null);

  const reload = () => api.notificationChannels().then(setChannels).catch(console.error);
  useEffect(() => {
    void reload();
  }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    const config =
      draft.type === "webhook"
        ? { url: draft.url }
        : { bot_token: draft.bot_token, chat_id: draft.chat_id };
    await api.createChannel({
      name: draft.name,
      type: draft.type,
      config,
      min_priority: draft.min_priority,
    });
    setCreating(false);
    setDraft(EMPTY);
    await reload();
  };

  return (
    <div className="space-y-4 p-5">
      <div className="flex items-center gap-3">
        <h1 className="font-display text-xl font-semibold">Notificaciones</h1>
        <button
          onClick={() => setCreating(true)}
          className="ml-auto flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white"
        >
          <Plus size={14} /> Nuevo canal
        </button>
      </div>

      {message && (
        <p className="rounded-md border border-line bg-panel px-4 py-2 font-mono text-xs text-mut">
          {message}
        </p>
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
          ) : (
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
          )}
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
            Sin canales. Crea uno para recibir alertas por webhook o Telegram.
          </p>
        )}
      </div>
    </div>
  );
}
