import { useEffect, useRef, useState } from "react";
import { auth } from "./api";

export interface WsAlert {
  kind?: "event" | "evidence_update";
  event_id: string;
  event_type?: string;
  priority?: "info" | "warning" | "critical";
  camera_id?: string;
  timestamp?: string;
  confidence?: number | null;
  rule_id?: string;
  object_id?: number | null;
  metadata: Record<string, unknown> | null;
  snapshot_key?: string | null;
  clip_key?: string | null;
  snapshot_url?: string | null;
  clip_url?: string | null;
}

function wsUrl(): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const token = auth.token();
  const qs = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${proto}://${location.host}/ws/alerts${qs}`;
}

/** WebSocket with exponential backoff reconnect; calls onAlert per message. */
export function useAlertsWs(onAlert: (a: WsAlert) => void) {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onAlert);
  handler.current = onAlert;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let delay = 1000;
    let closed = false;
    let timer: ReturnType<typeof setTimeout>;

    const connect = () => {
      if (closed) return;
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        setConnected(true);
        delay = 1000;
      };
      ws.onmessage = (e) => {
        try {
          handler.current(JSON.parse(e.data) as WsAlert);
        } catch {
          /* malformed frame */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) {
          timer = setTimeout(connect, delay);
          delay = Math.min(delay * 2, 15000);
        }
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return connected;
}
