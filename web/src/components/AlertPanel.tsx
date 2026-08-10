import { Bell, BellRing, Check, Volume2, VolumeX } from "lucide-react";
import { useState } from "react";
import type { EventItem } from "../lib/api";
import { subscribeToPushes, pushSupported } from "../lib/push";
import {
  CLASS_ICONS,
  EVENT_LABELS,
  SEVERITY_DOT,
  fmtTime,
  relTime,
} from "../lib/format";

export interface AlertEntry extends EventItem {
  live?: boolean;
}

function AlertRow({
  alert,
  now,
  onAck,
}: {
  alert: AlertEntry;
  now: number;
  onAck: (id: string) => void;
}) {
  const meta = alert.metadata ?? {};
  const cls = String(meta.vehicle_class ?? "");
  const Icon = CLASS_ICONS[cls];
  const acked = Boolean(alert.acknowledged_at);
  return (
    <div
      className={`group flex gap-3 border-b border-line/60 px-4 py-3 ${alert.live ? "alert-enter" : ""} ${acked ? "opacity-50" : ""}`}
    >
      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${SEVERITY_DOT[alert.priority]}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-display text-sm font-medium">
            {EVENT_LABELS[alert.event_type] ?? alert.event_type}
          </span>
          <span className="shrink-0 font-mono text-[10px] text-mut" title={fmtTime(alert.timestamp)}>
            {relTime(alert.timestamp, now)}
          </span>
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-xs text-mut">
          {Icon && <Icon size={13} />}
          {alert.rule_id && <span className="truncate font-mono text-[11px]">{alert.rule_id}</span>}
          {typeof meta.speed_kmh === "number" && (
            <span className="font-mono text-[11px]">{meta.speed_kmh} km/h</span>
          )}
        </div>
        {acked && (
          <div className="mt-0.5 font-mono text-[10px] text-info">
            acusada por {alert.acknowledged_by}
          </div>
        )}
      </div>
      {!acked && alert.priority !== "info" && (
        <button
          onClick={() => onAck(alert.event_id)}
          title="Acusar recibo"
          className="self-center rounded border border-line p-1.5 text-mut opacity-0 transition-opacity hover:border-info hover:text-info group-hover:opacity-100"
        >
          <Check size={13} />
        </button>
      )}
      {alert.snapshot_url && (
        <img
          src={alert.snapshot_url}
          alt="evidencia"
          className="h-12 w-20 shrink-0 rounded border border-line object-cover"
        />
      )}
    </div>
  );
}

export default function AlertPanel({
  alerts,
  soundOn,
  onToggleSound,
  onAck,
}: {
  alerts: AlertEntry[];
  soundOn: boolean;
  onToggleSound: () => void;
  onAck: (id: string) => void;
}) {
  const [now] = useState(() => Date.now());
  const [pushState, setPushState] = useState<"off" | "on" | "loading">("off");
  return (
    <div className="flex h-full flex-col border-l border-line bg-panel">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 className="font-display text-sm font-semibold tracking-wide">ALERTAS</h2>
        <div className="flex items-center gap-1">
          {pushSupported() && (
            <button
              onClick={() => {
                setPushState("loading");
                void subscribeToPushes().then((s) =>
                  setPushState(s === "subscribed" ? "on" : "off"),
                );
              }}
              className="rounded p-1.5 text-mut transition-colors hover:bg-raised hover:text-ink"
              title="Notificaciones push (PWA)"
            >
              {pushState === "on" ? (
                <BellRing size={15} className="text-info" />
              ) : (
                <Bell size={15} className={pushState === "loading" ? "animate-pulse" : ""} />
              )}
            </button>
          )}
          <button
            onClick={onToggleSound}
            className="rounded p-1.5 text-mut transition-colors hover:bg-raised hover:text-ink"
            title={soundOn ? "Silenciar alertas" : "Activar sonido de alertas"}
          >
            {soundOn ? <Volume2 size={15} /> : <VolumeX size={15} />}
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {alerts.length === 0 ? (
          <div className="px-4 py-10 text-center">
            <p className="text-sm text-mut">Sin alertas recientes</p>
            <p className="mt-1 text-xs text-dim">
              Las alertas de las reglas activas aparecerán aquí en tiempo real.
            </p>
          </div>
        ) : (
          alerts.map((a) => <AlertRow key={a.event_id} alert={a} now={now} onAck={onAck} />)
        )}
      </div>
    </div>
  );
}
