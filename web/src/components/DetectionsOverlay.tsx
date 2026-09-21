import { useEffect, useRef } from "react";
import { api, type DetectionsPayload } from "../lib/api";

// COCO skeleton edges (body only — no face, for privacy)
const EDGES: [number, number][] = [
  [5, 7], [7, 9], [6, 8], [8, 10], // arms
  [5, 6], [11, 12], [5, 11], [6, 12], // torso
  [11, 13], [13, 15], [12, 14], [14, 16], // legs
];

const POSTURE_COLOR: Record<string, string> = {
  standing: "#22c55e",
  sitting: "#3b82f6",
  fallen: "#ef4444",
  unknown: "#eab308",
};

export type AnalyticsState = "connecting" | "live" | "stale" | "unavailable";

// Compensacion de latencia: entre cada respuesta (300 ms) el recuadro avanza
// por velocidad muerta (dead reckoning) a 60 fps, dibujandolo donde el objeto
// esta AHORA en el video en vez de donde estaba cuando se proceso el frame.
const DR_HORIZON_S = 2.5; // no extrapolar mas alla de 2.5 s sin datos frescos

type VelState = { x: number; y: number; t: number; vx: number; vy: number };

export default function DetectionsOverlay({
  cameraId,
  onState,
  profile,
}: {
  cameraId: string;
  onState?: (state: AnalyticsState) => void;
  /** people: solo dibuja personas (evita ruido de clases irrelevantes en interiores) */
  profile?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dataRef = useRef<DetectionsPayload | null>(null);
  const velRef = useRef<Map<string, VelState>>(new Map());

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let raf = 0;

    const updateVelocities = (d: DetectionsPayload) => {
      const ts = Number(d.ts ?? Date.now() / 1000);
      for (const o of d.objects) {
        const key = `${o.id}`;
        const [nx1, ny1, nx2, ny2] = o.box;
        const cx = (nx1 + nx2) / 2;
        const cy = (ny1 + ny2) / 2;
        const prev = velRef.current.get(key);
        if (prev) {
          const dt = ts - prev.t;
          if (dt > 0.01) {
            const ivx = (cx - prev.x) / dt;
            const ivy = (cy - prev.y) / dt;
            // EMA para suavizar el ruido entre polls
            prev.vx = prev.vx * 0.5 + ivx * 0.5;
            prev.vy = prev.vy * 0.5 + ivy * 0.5;
            prev.x = cx;
            prev.y = cy;
            prev.t = ts;
          }
        } else {
          velRef.current.set(key, { x: cx, y: cy, t: ts, vx: 0, vy: 0 });
        }
      }
      // limpiar IDs que ya no estan
      const seen = new Set(d.objects.map((o) => `${o.id}`));
      for (const k of velRef.current.keys()) {
        if (!seen.has(k)) velRef.current.delete(k);
      }
    };

    const draw = () => {
      const d = dataRef.current;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const w = Math.max(1, rect.width);
      const h = Math.max(1, rect.height);
      if (canvas.width !== Math.round(w)) canvas.width = Math.round(w);
      if (canvas.height !== Math.round(h)) canvas.height = Math.round(h);
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.clearRect(0, 0, w, h);
      if (!d?.objects?.length) return;

      const nowEpoch = Date.now() / 1000;
      const dataTs = Number(d.ts ?? nowEpoch);
      const drift = Math.min(nowEpoch - dataTs, DR_HORIZON_S);

      for (const o of d.objects) {
        if (profile === "people" && o.class && o.class.toLowerCase() !== "person") continue;
        let [nx1, ny1, nx2, ny2] = o.box;
        const key = `${o.id}`;
        const v = velRef.current.get(key);
        if (v && drift > 0 && drift <= DR_HORIZON_S) {
          // dead reckoning: proyectar el centro con la ultima velocidad
          const cx = (nx1 + nx2) / 2 + v.vx * drift;
          const cy = (ny1 + ny2) / 2 + v.vy * drift;
          nx1 += cx - (nx1 + nx2) / 2;
          nx2 += cx - (nx1 + nx2) / 2;
          ny1 += cy - (ny1 + ny2) / 2;
          ny2 += cy - (ny1 + ny2) / 2;
        }
        const x = nx1 * w, y = ny1 * h, bw = (nx2 - nx1) * w, bh = (ny2 - ny1) * h;
        const color = POSTURE_COLOR[o.posture ?? "unknown"] ?? "#eab308";
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.strokeRect(x, y, bw, bh);
        if (o.keypoints?.length) {
          ctx.strokeStyle = color;
          ctx.lineWidth = 2;
          for (const [a, b] of EDGES) {
            if (a >= o.keypoints.length || b >= o.keypoints.length) continue;
            const pa = o.keypoints[a], pb = o.keypoints[b];
            if (!pa || !pb) continue;
            ctx.beginPath();
            ctx.moveTo(pa[0] * w, pa[1] * h);
            ctx.lineTo(pb[0] * w, pb[1] * h);
            ctx.stroke();
          }
        }
        const detail = o.vehicle_type ?? o.posture;
        const label = `${o.class} #${o.id}${detail ? ` · ${detail}` : ""}`;
        ctx.font = "600 11px ui-monospace, monospace";
        const tw = ctx.measureText(label).width + 8;
        ctx.fillStyle = "rgba(0,0,0,0.65)";
        ctx.fillRect(x, Math.max(0, y - 16), tw, 16);
        ctx.fillStyle = color;
        ctx.fillText(label, x + 4, Math.max(11, y - 4));
      }
    };

    const rafLoop = () => {
      draw();
      raf = requestAnimationFrame(rafLoop);
    };

    const load = () => {
      void api
        .detections(cameraId)
        .then((d) => {
          if (!alive) return;
          updateVelocities(d);
          dataRef.current = d;
          onState?.(d.status);
        })
        .catch(() => alive && onState?.("unavailable"))
        .finally(() => {
          // Never overlap requests. A fixed interval can exhaust browser and
          // API connections when one response is delayed or a camera drops.
          if (alive) timer = setTimeout(load, 300);
        });
    };
    load();
    raf = requestAnimationFrame(rafLoop);
    const onResize = () => draw();
    window.addEventListener("resize", onResize);
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      if (timer) clearTimeout(timer);
      window.removeEventListener("resize", onResize);
    };
  }, [cameraId, onState]);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0 z-10 h-full w-full"
    />
  );
}
