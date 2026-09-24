import { useEffect, useRef } from "react";
import { api, type DetectionsPayload } from "../lib/api";

// COCO skeleton edges (body only — no face, for privacy)
const EDGES: [number, number][] = [
  [5, 7], [7, 9], [6, 8], [8, 10], // arms
  [5, 6], [11, 12], [5, 11], [6, 12], // torso
  [11, 13], [13, 15], [12, 14], [14, 16], // legs
];

// paleta: sentada verde, caminando morado, de pie rojo
const POSTURE_COLOR: Record<string, string> = {
  sitting: "#22c55e",
  moving: "#d946ef",
  standing: "#ef4444",
  fallen: "#f97316",
  unknown: "#eab308",
};

export type AnalyticsState = "connecting" | "live" | "stale" | "unavailable";

// Compensacion de latencia: entre cada respuesta (300 ms) el recuadro avanza
// por velocidad muerta (dead reckoning) a 60 fps, dibujandolo donde el objeto
// esta AHORA en el video en vez de donde estaba cuando se proceso el frame.
const DR_HORIZON_S = 2.5; // no extrapolar mas alla de 2.5 s sin datos frescos
// Latencia del reproductor de video (WHEP) respecto al tiempo real: los
// recuadros se dibujan en la posicion estimada para ese instante del video.
const VIDEO_LATENCY_S = 0.65;
// Suavizado del render: velocidad con la que el recuadro persigue su
// posicion proyectada (por segundo). Mayor = sigue mas rapido.
const CHASE_RATE = 10;
const VEL_ALPHA = 0.6;
const SPEED_FLOOR = 0.045;

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
  const renderRef = useRef<Map<string, { x: number; y: number; w: number; h: number; trail: { x: number; y: number }[] }>>(new Map());

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
            prev.vx = prev.vx * (1 - VEL_ALPHA) + ivx * VEL_ALPHA;
            prev.vy = prev.vy * (1 - VEL_ALPHA) + ivy * VEL_ALPHA;
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
      for (const k of renderRef.current.keys()) {
        if (!seen.has(k)) renderRef.current.delete(k);
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
      // instante del video que el usuario esta viendo (video va atrasado
      // su propia latencia WHEP): los recuadros se proyectan a ese instante
      const projTime = Math.min(nowEpoch - VIDEO_LATENCY_S, dataTs + DR_HORIZON_S);
      const drift = Math.max(0, projTime - dataTs);

      for (const o of d.objects) {
        if (profile === "people" && o.class && o.class.toLowerCase() !== "person") continue;
        let [nx1, ny1, nx2, ny2] = o.box;
        const key = `${o.id}`;
        const v = velRef.current.get(key);
        if (v && Math.hypot(v.vx, v.vy) < SPEED_FLOOR) {
          v.vx = 0;
          v.vy = 0;
        }
        if (v) {
          // dead reckoning: proyectar el centro con la ultima velocidad
          const cx = (nx1 + nx2) / 2 + v.vx * drift;
          const cy = (ny1 + ny2) / 2 + v.vy * drift;
          nx1 += cx - (nx1 + nx2) / 2;
          nx2 += cx - (nx1 + nx2) / 2;
          ny1 += cy - (ny1 + ny2) / 2;
          ny2 += cy - (ny1 + ny2) / 2;
        }
        // tamano suavizado (EMA 0.3): reduce el parpadeo del box
        const rp0 = renderRef.current.get(key);
        const nw = rp0 ? rp0.w * 0.7 + (nx2 - nx1) * 0.3 : nx2 - nx1;
        const nh = rp0 ? rp0.h * 0.7 + (ny2 - ny1) * 0.3 : ny2 - ny1;
        nx2 = nx1 + nw;
        ny2 = ny1 + nh;
        // persecucion suavizada del render: el recuadro dibujado persigue
        // la proyeccion a CHASE_RATE por segundo (movimiento fluido a 60fps)
        const rp = renderRef.current.get(key);
        if (rp) {
          const k = Math.min(1, CHASE_RATE * (1 / 60));
          const dcx = (nx1 + nx2) / 2 - rp.x;
          const dcy = (ny1 + ny2) / 2 - rp.y;
          rp.x += dcx * k;
          rp.y += dcy * k;
          rp.w = nw; rp.h = nh;
          nx1 = rp.x - nw / 2;
          nx2 = rp.x + nw / 2;
          ny1 = rp.y - nh / 2;
          ny2 = rp.y + nh / 2;
          rp.trail.push({ x: rp.x, y: rp.y });
          if (rp.trail.length > 8) rp.trail.shift();
          for (let ti = 0; ti < rp.trail.length; ti++) {
            const p = rp.trail[ti];
            ctx.fillStyle = "rgba(234,179,8," + (0.12 + 0.5 * (ti / rp.trail.length)) + ")";
            ctx.beginPath();
            ctx.arc(p.x * w, p.y * h, 3, 0, Math.PI * 2);
            ctx.fill();
          }
        } else {
          renderRef.current.set(key, { x: (nx1 + nx2) / 2, y: (ny1 + ny2) / 2, w: nx2 - nx1, h: ny2 - ny1, trail: [] });
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
          if (alive) timer = setTimeout(load, 150);
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
