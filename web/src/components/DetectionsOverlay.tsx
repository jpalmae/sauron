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

export default function DetectionsOverlay({
  cameraId,
  onState,
}: {
  cameraId: string;
  onState?: (state: AnalyticsState) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let latest: DetectionsPayload | null = null;
    const draw = (d: DetectionsPayload | null) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const w = Math.max(1, rect.width);
      const h = Math.max(1, rect.height);
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.clearRect(0, 0, w, h);
      if (!d?.objects?.length) return;

      for (const o of d.objects) {
        const [nx1, ny1, nx2, ny2] = o.box;
        const x = nx1 * w, y = ny1 * h, bw = (nx2 - nx1) * w, bh = (ny2 - ny1) * h;
        const color = POSTURE_COLOR[o.posture ?? "unknown"] ?? "#eab308";
        // box
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.strokeRect(x, y, bw, bh);
        // skeleton
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
        // label
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

    const load = () => {
      void api
        .detections(cameraId)
        .then((d) => {
          if (!alive) return;
          latest = d;
          draw(d);
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
    const onResize = () => draw(latest);
    window.addEventListener("resize", onResize);
    return () => {
      alive = false;
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
