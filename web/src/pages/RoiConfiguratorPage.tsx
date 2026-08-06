import {
  Hexagon,
  ImageUp,
  MousePointer2,
  MoveRight,
  Save,
  Spline,
  Trash2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  api,
  type Camera,
  type RoiConfig,
  type RoiLine,
  type RoiPolygon,
} from "../lib/api";
import {
  centroid,
  directionFromClick,
  hitTestLine,
  hitTestPolygon,
  homographyDst,
  lineMid,
  type Pt,
} from "../lib/roi";

type Tool = "select" | "polygon" | "line" | "direction" | "homography" | "delete";

const DEFAULT_THRESHOLDS: Record<string, number> = {
  stopped_seconds: 15,
  wrong_way_seconds: 3,
  wrong_way_cosine: -0.7,
  congestion_occupancy: 0.6,
  congestion_seconds: 30,
};

const ALL_RULES = ["stopped", "wrong_way", "congestion"] as const;

export default function RoiConfiguratorPage() {
  const { id } = useParams<{ id: string }>();
  const [camera, setCamera] = useState<Camera | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imgSize, setImgSize] = useState<Pt>([1280, 720]);
  const [polygons, setPolygons] = useState<RoiPolygon[]>([]);
  const [lines, setLines] = useState<RoiLine[]>([]);
  const [homographySrc, setHomographySrc] = useState<Pt[]>([]);
  const [homoMeters, setHomoMeters] = useState<{ w: number; h: number }>({ w: 25, h: 10 });
  const [thresholds, setThresholds] = useState(DEFAULT_THRESHOLDS);
  const [tool, setTool] = useState<Tool>("select");
  const [draft, setDraft] = useState<Pt[]>([]);
  const [selected, setSelected] = useState<{ type: "polygon" | "line"; idx: number } | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!id) return;
    api.cameras().then(async (cams) => {
      const cam = cams.find((c) => c.id === id) ?? null;
      setCamera(cam);
      const roi = cam?.roi_config;
      if (roi) {
        setPolygons(roi.polygons ?? []);
        setLines(roi.lines ?? []);
        setHomographySrc((roi.homography?.src_points as Pt[]) ?? []);
        setThresholds({ ...DEFAULT_THRESHOLDS, ...(roi.thresholds ?? {}) });
      }
      // best-effort background frame: latest event snapshot for this camera
      try {
        const page = await api.events({ camera_id: id }, 1, 20);
        const withSnap = page.items.find((e) => e.snapshot_url);
        if (withSnap?.snapshot_url) setImageUrl(withSnap.snapshot_url);
      } catch {
        /* no snapshot yet */
      }
    });
  }, [id]);

  const toImageCoords = (e: React.MouseEvent<SVGSVGElement>): Pt => {
    const rect = svgRef.current!.getBoundingClientRect();
    return [
      Math.round(((e.clientX - rect.left) / rect.width) * imgSize[0]),
      Math.round(((e.clientY - rect.top) / rect.height) * imgSize[1]),
    ];
  };

  const onCanvasClick = (e: React.MouseEvent<SVGSVGElement>) => {
    const p = toImageCoords(e);
    if (tool === "polygon") {
      setDraft((d) => [...d, p]);
    } else if (tool === "line") {
      const next = [...draft, p];
      setDraft(next);
      if (next.length === 2) {
        setLines((ls) => [...ls, { id: `L${ls.length + 1}`, points: next }]);
        setDraft([]);
      }
    } else if (tool === "homography") {
      setHomographySrc((pts) => (pts.length >= 4 ? pts : [...pts, p]));
    } else if (tool === "direction" && selected) {
      const anchor =
        selected.type === "polygon"
          ? centroid(polygons[selected.idx].points as Pt[])
          : lineMid(lines[selected.idx]);
      const dir = directionFromClick(anchor, p);
      if (selected.type === "polygon") {
        setPolygons((ps) => ps.map((x, i) => (i === selected.idx ? { ...x, direction: dir } : x)));
      } else {
        setLines((ls) => ls.map((x, i) => (i === selected.idx ? { ...x, direction: dir } : x)));
      }
      setTool("select");
    } else if (tool === "delete") {
      const pIdx = polygons.findIndex((poly) => hitTestPolygon(p, poly));
      if (pIdx >= 0) {
        setPolygons((ps) => ps.filter((_, i) => i !== pIdx));
        return;
      }
      const lIdx = lines.findIndex((l) => hitTestLine(p, l, 12));
      if (lIdx >= 0) setLines((ls) => ls.filter((_, i) => i !== lIdx));
    } else if (tool === "select") {
      const pIdx = polygons.findIndex((poly) => hitTestPolygon(p, poly));
      if (pIdx >= 0) {
        setSelected({ type: "polygon", idx: pIdx });
        return;
      }
      const lIdx = lines.findIndex((l) => hitTestLine(p, l, 12));
      setSelected(lIdx >= 0 ? { type: "line", idx: lIdx } : null);
    }
  };

  const closePolygonDraft = () => {
    if (draft.length >= 3) {
      setPolygons((ps) => [
        ...ps,
        { id: `lane-${ps.length + 1}`, points: draft, kind: "lane", rules: ["stopped"] },
      ]);
      setSelected({ type: "polygon", idx: polygons.length });
    }
    setDraft([]);
  };

  const save = async () => {
    if (!camera) return;
    const roi_config: RoiConfig = { lines, polygons, thresholds };
    if (homographySrc.length === 4) {
      roi_config.homography = {
        src_points: homographySrc,
        dst_points: homographyDst(homoMeters.w, homoMeters.h),
      };
    }
    await api.updateCamera(camera.id, { roi_config });
    setSavedAt(new Date().toLocaleTimeString("es-CL", { hour12: false }));
  };

  const TOOLS: { key: Tool; label: string; icon: typeof Spline; hint: string }[] = [
    { key: "select", label: "Seleccionar", icon: MousePointer2, hint: "click sobre una figura" },
    { key: "polygon", label: "Polígono", icon: Hexagon, hint: "click por vértice, luego Cerrar" },
    { key: "line", label: "Línea", icon: Spline, hint: "2 clicks: inicio y fin" },
    { key: "direction", label: "Dirección", icon: MoveRight, hint: "click hacia el flujo permitido" },
    { key: "homography", label: "Homografía", icon: ImageUp, hint: "4 puntos (esquinas)" },
    { key: "delete", label: "Borrar", icon: Trash2, hint: "click sobre la figura" },
  ];

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h1 className="font-display text-lg font-semibold">
            ROI — {camera?.name ?? "…"}
          </h1>
          <div className="ml-auto flex items-center gap-1.5">
            {TOOLS.map(({ key, label, icon: Icon, hint }) => (
              <button
                key={key}
                title={`${label}: ${hint}`}
                onClick={() => {
                  setTool(key);
                  setDraft([]);
                }}
                className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
                  tool === key
                    ? "border-brand bg-brand/15 text-ink"
                    : "border-line text-mut hover:text-ink"
                }`}
              >
                <Icon size={14} /> {label}
              </button>
            ))}
            <label className="flex cursor-pointer items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-xs text-mut hover:text-ink">
              <ImageUp size={14} /> Frame
              <input
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) setImageUrl(URL.createObjectURL(f));
                }}
              />
            </label>
          </div>
        </div>

        <div className="relative min-h-0 flex-1 overflow-hidden rounded-lg border border-line bg-panel">
          {imageUrl ? (
            <img
              src={imageUrl}
              alt="frame"
              className="absolute inset-0 h-full w-full object-contain"
              onLoad={(e) =>
                setImgSize([
                  e.currentTarget.naturalWidth || 1280,
                  e.currentTarget.naturalHeight || 720,
                ])
              }
            />
          ) : (
            <div className="absolute inset-0 grid place-items-center text-center">
              <p className="max-w-xs text-sm text-dim">
                Sin frame de fondo. Sube una imagen de la cámara para dibujar las zonas con
                precisión.
              </p>
            </div>
          )}
          <svg
            ref={svgRef}
            viewBox={`0 0 ${imgSize[0]} ${imgSize[1]}`}
            className="absolute inset-0 h-full w-full cursor-crosshair"
            onClick={onCanvasClick}
            onDoubleClick={tool === "polygon" ? closePolygonDraft : undefined}
          >
            {polygons.map((poly, i) => (
              <g key={`p${i}`}>
                <polygon
                  points={poly.points.map((p) => p.join(",")).join(" ")}
                  fill={
                    selected?.type === "polygon" && selected.idx === i
                      ? "var(--color-brand)"
                      : "var(--color-info)"
                  }
                  fillOpacity={0.12}
                  stroke={
                    selected?.type === "polygon" && selected.idx === i
                      ? "var(--color-brand)"
                      : "var(--color-info)"
                  }
                  strokeWidth={2}
                />
                <text
                  x={centroid(poly.points as Pt[])[0]}
                  y={centroid(poly.points as Pt[])[1]}
                  fill="var(--color-ink)"
                  fontSize={16}
                  fontFamily="var(--font-mono)"
                  textAnchor="middle"
                >
                  {poly.id}
                </text>
                {poly.direction && (
                  <DirectionArrow from={centroid(poly.points as Pt[])} dir={poly.direction as Pt} />
                )}
              </g>
            ))}
            {lines.map((line, i) => (
              <g key={`l${i}`}>
                <line
                  x1={line.points[0][0]}
                  y1={line.points[0][1]}
                  x2={line.points[1]?.[0]}
                  y2={line.points[1]?.[1]}
                  stroke={
                    selected?.type === "line" && selected.idx === i
                      ? "var(--color-brand)"
                      : "var(--color-warn)"
                  }
                  strokeWidth={3}
                />
                <text
                  x={lineMid(line)[0]}
                  y={lineMid(line)[1] - 8}
                  fill="var(--color-warn)"
                  fontSize={14}
                  fontFamily="var(--font-mono)"
                  textAnchor="middle"
                >
                  {line.id}
                </text>
                {line.direction && (
                  <DirectionArrow from={lineMid(line)} dir={line.direction as Pt} />
                )}
              </g>
            ))}
            {homographySrc.map((p, i) => (
              <g key={`h${i}`}>
                <circle cx={p[0]} cy={p[1]} r={6} fill="var(--color-brand-accent)" />
                <text x={p[0] + 10} y={p[1] - 6} fill="var(--color-brand-accent)" fontSize={13} fontFamily="var(--font-mono)">
                  H{i + 1}
                </text>
              </g>
            ))}
            {draft.length > 0 && (
              <polyline
                points={draft.map((p) => p.join(",")).join(" ")}
                fill="none"
                stroke="var(--color-ink)"
                strokeDasharray="6 4"
                strokeWidth={2}
              />
            )}
          </svg>
        </div>

        {tool === "polygon" && draft.length >= 3 && (
          <button
            onClick={closePolygonDraft}
            className="mt-2 self-start rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-white"
          >
            Cerrar polígono ({draft.length} vértices)
          </button>
        )}
      </div>

      <div className="w-80 shrink-0 space-y-4 overflow-y-auto border-l border-line bg-panel p-4">
        <section>
          <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-mut">
            Figuras ({polygons.length + lines.length})
          </h3>
          <div className="space-y-2">
            {polygons.map((poly, i) => (
              <div
                key={i}
                className={`rounded-md border p-2.5 text-xs ${
                  selected?.type === "polygon" && selected.idx === i
                    ? "border-brand"
                    : "border-line"
                }`}
              >
                <div className="flex items-center gap-2">
                  <input
                    value={poly.id}
                    onChange={(e) =>
                      setPolygons((ps) =>
                        ps.map((x, j) => (j === i ? { ...x, id: e.target.value } : x)),
                      )
                    }
                    className="w-24 rounded border border-line bg-base px-2 py-1 font-mono"
                  />
                  <select
                    value={poly.kind ?? "lane"}
                    onChange={(e) =>
                      setPolygons((ps) =>
                        ps.map((x, j) =>
                          j === i ? { ...x, kind: e.target.value as RoiPolygon["kind"] } : x,
                        ),
                      )
                    }
                    className="rounded border border-line bg-base px-2 py-1"
                  >
                    <option value="lane">carril</option>
                    <option value="parking">estacionamiento</option>
                    <option value="counting">conteo</option>
                  </select>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {ALL_RULES.map((rule) => (
                    <label key={rule} className="flex items-center gap-1 font-mono text-[10px] text-mut">
                      <input
                        type="checkbox"
                        checked={poly.rules?.includes(rule) ?? false}
                        onChange={(e) =>
                          setPolygons((ps) =>
                            ps.map((x, j) =>
                              j === i
                                ? {
                                    ...x,
                                    rules: e.target.checked
                                      ? [...(x.rules ?? []), rule]
                                      : (x.rules ?? []).filter((r) => r !== rule),
                                  }
                                : x,
                            ),
                          )
                        }
                      />
                      {rule}
                    </label>
                  ))}
                </div>
                {poly.rules?.includes("wrong_way") && !poly.direction && (
                  <p className="mt-1.5 font-mono text-[10px] text-warn">
                    falta dirección: selecciona la figura y usa la herramienta Dirección
                  </p>
                )}
              </div>
            ))}
            {lines.map((line, i) => (
              <div
                key={i}
                className={`rounded-md border p-2.5 text-xs ${
                  selected?.type === "line" && selected.idx === i ? "border-brand" : "border-line"
                }`}
              >
                <input
                  value={line.id}
                  onChange={(e) =>
                    setLines((ls) => ls.map((x, j) => (j === i ? { ...x, id: e.target.value } : x)))
                  }
                  className="w-24 rounded border border-line bg-base px-2 py-1 font-mono"
                />
                <span className="ml-2 font-mono text-[10px] text-mut">
                  línea de conteo {line.direction ? "· con dirección" : ""}
                </span>
              </div>
            ))}
            {polygons.length + lines.length === 0 && (
              <p className="text-xs text-dim">
                Dibuja una línea de conteo o un polígono de carril sobre el frame.
              </p>
            )}
          </div>
        </section>

        <section>
          <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-mut">
            Homografía (velocidad)
          </h3>
          {homographySrc.length === 4 ? (
            <div className="flex items-center gap-2 text-xs">
              <label className="text-mut">ancho real (m)</label>
              <input
                type="number"
                value={homoMeters.w}
                onChange={(e) => setHomoMeters((m) => ({ ...m, w: Number(e.target.value) }))}
                className="w-16 rounded border border-line bg-base px-2 py-1 font-mono"
              />
              <label className="text-mut">alto (m)</label>
              <input
                type="number"
                value={homoMeters.h}
                onChange={(e) => setHomoMeters((m) => ({ ...m, h: Number(e.target.value) }))}
                className="w-16 rounded border border-line bg-base px-2 py-1 font-mono"
              />
            </div>
          ) : (
            <p className="text-xs text-dim">
              Marca 4 puntos con la herramienta Homografía ({homographySrc.length}/4).
            </p>
          )}
        </section>

        <section>
          <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-mut">
            Umbrales
          </h3>
          <div className="grid grid-cols-2 gap-2">
            {Object.entries(thresholds).map(([key, value]) => (
              <label key={key} className="text-[11px] text-mut">
                {key}
                <input
                  type="number"
                  step="any"
                  value={value}
                  onChange={(e) =>
                    setThresholds((t) => ({ ...t, [key]: Number(e.target.value) }))
                  }
                  className="mt-0.5 w-full rounded border border-line bg-base px-2 py-1 font-mono text-xs"
                />
              </label>
            ))}
          </div>
        </section>

        <button
          onClick={save}
          className="flex w-full items-center justify-center gap-2 rounded-md bg-brand px-4 py-2.5 text-sm font-medium text-white"
        >
          <Save size={15} /> Guardar configuración
        </button>
        {savedAt && (
          <p className="text-center font-mono text-[11px] text-info">guardado {savedAt}</p>
        )}
      </div>
    </div>
  );
}

function DirectionArrow({ from, dir }: { from: Pt; dir: Pt }) {
  const len = 60;
  const to: Pt = [from[0] + dir[0] * len, from[1] + dir[1] * len];
  return (
    <g>
      <line
        x1={from[0]}
        y1={from[1]}
        x2={to[0]}
        y2={to[1]}
        stroke="var(--color-brand-accent)"
        strokeWidth={3}
        markerEnd="url(#arrowhead)"
      />
      <defs>
        <marker id="arrowhead" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 z" fill="var(--color-brand-accent)" />
        </marker>
      </defs>
    </g>
  );
}
