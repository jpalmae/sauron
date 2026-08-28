import {
  Hexagon,
  ImageUp,
  MousePointer2,
  MoveRight,
  Pause,
  Play,
  RefreshCw,
  Save,
  Spline,
  Trash2,
  Undo2,
  Video,
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

type DragStart = (
  e: React.PointerEvent,
  type: "line" | "polygon" | "homography",
  idx: number,
  vertex: number | null,
) => void;

function RoiCanvas(props: {
  svgRef: React.RefObject<SVGSVGElement | null>;
  imgSize: Pt;
  tool: Tool;
  polygons: RoiPolygon[];
  lines: RoiLine[];
  homographySrc: Pt[];
  draft: Pt[];
  selected: { type: "polygon" | "line"; idx: number } | null;
  cursorPt?: Pt | null;
  onCanvasClick: (e: React.MouseEvent<SVGSVGElement>) => void;
  onDoubleClick?: () => void;
  onPointerMove: (e: React.PointerEvent<SVGSVGElement>) => void;
  onPointerUp: () => void;
  onPointerLeave: () => void;
  onContextMenu: (e: React.MouseEvent) => void;
  beginDrag: DragStart;
}) {
  const {
    svgRef, imgSize, tool, polygons, lines, homographySrc, draft, selected, cursorPt,
    onCanvasClick, onDoubleClick, onPointerMove, onPointerUp, onPointerLeave,
    onContextMenu, beginDrag,
  } = props;
  const selectable = tool === "select";
  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${imgSize[0]} ${imgSize[1]}`}
      className="absolute inset-0 h-full w-full cursor-crosshair"
      onClick={onCanvasClick}
      onDoubleClick={onDoubleClick}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerLeave}
      onContextMenu={onContextMenu}
    >
      {polygons.map((poly, i) => {
        const isSel = selected?.type === "polygon" && selected.idx === i;
        return (
          <g key={`p${i}`}>
            <polygon
              points={poly.points.map((p) => p.join(",")).join(" ")}
              fill={isSel ? "var(--color-brand)" : "var(--color-info)"}
              fillOpacity={0.12}
              stroke={isSel ? "var(--color-brand)" : "var(--color-info)"}
              strokeWidth={2}
              style={selectable ? { cursor: "move" } : undefined}
              onPointerDown={(e) => beginDrag(e, "polygon", i, null)}
            />
            <text
              x={centroid(poly.points as Pt[])[0]}
              y={centroid(poly.points as Pt[])[1]}
              fill="var(--color-ink)"
              fontSize={16}
              fontFamily="var(--font-mono)"
              textAnchor="middle"
              className="pointer-events-none"
            >
              {poly.id}
            </text>
            {poly.direction && (
              <DirectionArrow from={centroid(poly.points as Pt[])} dir={poly.direction as Pt} />
            )}
            {isSel &&
              (poly.points as Pt[]).map((pt, vi) => (
                <circle
                  key={`pv${vi}`}
                  cx={pt[0]}
                  cy={pt[1]}
                  r={7}
                  fill="var(--color-brand)"
                  stroke="#fff"
                  strokeWidth={2}
                  style={{ cursor: "grab" }}
                  onPointerDown={(e) => beginDrag(e, "polygon", i, vi)}
                />
              ))}
          </g>
        );
      })}
      {lines.map((line, i) => {
        const isSel = selected?.type === "line" && selected.idx === i;
        const [a, b] = line.points as Pt[];
        return (
          <g key={`l${i}`}>
            <line
              x1={a[0]}
              y1={a[1]}
              x2={b?.[0]}
              y2={b?.[1]}
              stroke="transparent"
              strokeWidth={16}
              style={selectable ? { cursor: "move" } : undefined}
              onPointerDown={(e) => beginDrag(e, "line", i, null)}
            />
            <line
              x1={a[0]}
              y1={a[1]}
              x2={b?.[0]}
              y2={b?.[1]}
              stroke={isSel ? "var(--color-brand)" : "var(--color-warn)"}
              strokeWidth={3}
              className="pointer-events-none"
            />
            <text
              x={lineMid(line)[0]}
              y={lineMid(line)[1] - 8}
              fill="var(--color-warn)"
              fontSize={14}
              fontFamily="var(--font-mono)"
              textAnchor="middle"
              className="pointer-events-none"
            >
              {line.id}
            </text>
            {line.direction && (
              <DirectionArrow from={lineMid(line)} dir={line.direction as Pt} />
            )}
            {isSel &&
              (line.points as Pt[]).map((pt, vi) => (
                <circle
                  key={`lv${vi}`}
                  cx={pt[0]}
                  cy={pt[1]}
                  r={7}
                  fill="var(--color-brand)"
                  stroke="#fff"
                  strokeWidth={2}
                  style={{ cursor: "grab" }}
                  onPointerDown={(e) => beginDrag(e, "line", i, vi)}
                />
              ))}
          </g>
        );
      })}
      {homographySrc.map((p, i) => (
        <g key={`h${i}`}>
          <circle
            cx={p[0]}
            cy={p[1]}
            r={7}
            fill="var(--color-brand-accent)"
            stroke="#fff"
            strokeWidth={2}
            style={selectable ? { cursor: "grab" } : undefined}
            onPointerDown={(e) => beginDrag(e, "homography", i, i)}
          />
          <text
            x={p[0] + 10}
            y={p[1] - 6}
            fill="var(--color-brand-accent)"
            fontSize={13}
            fontFamily="var(--font-mono)"
            className="pointer-events-none"
          >
            H{i + 1}
          </text>
        </g>
      ))}
      {draft.length > 0 && (
        <>
          <polyline
            points={draft.map((p) => p.join(",")).join(" ")}
            fill="none"
            stroke="var(--color-ink)"
            strokeDasharray="6 4"
            strokeWidth={2}
            className="pointer-events-none"
          />
          {draft.length >= 3 && (
            <circle
              cx={draft[0][0]}
              cy={draft[0][1]}
              r={10}
              fill="none"
              stroke="var(--color-ink)"
              strokeWidth={2}
              className="pointer-events-none"
            />
          )}
          {cursorPt && (
            <line
              x1={draft[draft.length - 1][0]}
              y1={draft[draft.length - 1][1]}
              x2={cursorPt[0]}
              y2={cursorPt[1]}
              stroke="var(--color-ink)"
              strokeOpacity={0.6}
              strokeDasharray="4 4"
              strokeWidth={2}
              className="pointer-events-none"
            />
          )}
          {draft.map((p, i) => (
            <circle
              key={`d${i}`}
              cx={p[0]}
              cy={p[1]}
              r={5}
              fill="var(--color-ink)"
              className="pointer-events-none"
            />
          ))}
        </>
      )}
      {draft.length === 0 && cursorPt && (tool === "line") && (
        <circle
          cx={cursorPt[0]}
          cy={cursorPt[1]}
          r={6}
          fill="none"
          stroke="var(--color-warn)"
          strokeWidth={2}
          className="pointer-events-none"
        />
      )}
    </svg>
  );
}

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
  const [drag, setDrag] = useState<{
    type: "line" | "polygon" | "homography";
    idx: number;
    vertex: number | null;
    origin: Pt;
    snapshot: Pt[];
  } | null>(null);
  const dragMovedRef = useRef(false);
  const [cursorPt, setCursorPt] = useState<Pt | null>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const [boxSize, setBoxSize] = useState<{ w: number; h: number } | null>(null);
  const [history, setHistory] = useState<
    { polygons: RoiPolygon[]; lines: RoiLine[]; homography: Pt[] }[]
  >([]);

  // escenario con alineacion exacta (JS, no CSS aspect) ante cualquier tamano de ventana
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const recompute = () => {
      const cw = el.clientWidth;
      const ch = el.clientHeight;
      if (!cw || !ch) return;
      const aspect = imgSize[0] / imgSize[1];
      let w = cw;
      let h = cw / aspect;
      if (h > ch) {
        h = ch;
        w = ch * aspect;
      }
      setBoxSize({ w, h });
    };
    recompute();
    const ro = new ResizeObserver(recompute);
    ro.observe(el);
    return () => ro.disconnect();
  }, [imgSize]);

  const snapshot = () =>
    setHistory((h) =>
      [...h.slice(-19), { polygons, lines, homography: homographySrc }],
    );
  const undo = () => {
    setHistory((h) => {
      if (h.length === 0) return h;
      const prev = h[h.length - 1];
      setPolygons(prev.polygons);
      setLines(prev.lines);
      setHomographySrc(prev.homography);
      setSelected(null);
      return h.slice(0, -1);
    });
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setDraft([]);
        setSelected(null);
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        undo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const grabLiveFrame = async (streamId: string): Promise<boolean> => {
    // live frame via go2rtc: /api/webrtc?src=X -> /api/frame.jpeg?src=X
    try {
      const s = await api.liveUrl(streamId);
      if (s.kind === "whep") {
        const frameUrl = s.url.replace("/api/webrtc?", "/api/frame.jpeg?");
        const resp = await fetch(frameUrl);
        if (!resp.ok) return false;
        const blob = await resp.blob();
        if (!blob.type.startsWith("image/")) return false;
        setImageUrl(URL.createObjectURL(blob));
        return true;
      }
    } catch {
      /* offline or unsupported */
    }
    return false;
  };

  // --- video en vivo como fondo del editor ---
  const [whepUrl, setWhepUrl] = useState<string | null>(null);
  const [liveMode, setLiveMode] = useState(false);
  const [frozen, setFrozen] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (!camera) return;
    api
      .liveUrl(camera.stream_id)
      .then((s) => setWhepUrl(s.kind === "whep" ? s.url : null))
      .catch(() => setWhepUrl(null));
  }, [camera]);

  useEffect(() => {
    if (!liveMode || !whepUrl || !videoRef.current) return;
    const pc = new RTCPeerConnection();
    let cancelled = false;
    (async () => {
      try {
        pc.addTransceiver("video", { direction: "recvonly" });
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        const resp = await fetch(whepUrl, {
          method: "POST",
          headers: { "Content-Type": "application/sdp" },
          body: offer.sdp,
        });
        if (!resp.ok) throw new Error(String(resp.status));
        await pc.setRemoteDescription({ type: "answer", sdp: await resp.text() });
      } catch {
        if (!cancelled) setLiveMode(false);
      }
    })();
    pc.ontrack = (e) => {
      if (videoRef.current) {
        videoRef.current.srcObject = e.streams[0];
        videoRef.current.onloadedmetadata = () => {
          const v = videoRef.current;
          if (!v) return;
          if (v.videoWidth) setImgSize([v.videoWidth, v.videoHeight]);
          void v.play().catch(() => undefined);
        };
      }
    };
    return () => {
      cancelled = true;
      pc.close();
    };
  }, [liveMode, whepUrl]);

  const toggleFreeze = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      v.play().catch(() => undefined);
      setFrozen(false);
    } else {
      v.pause();
      setFrozen(true);
    }
  };

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
      // live camera frame first; latest event snapshot as fallback
      const live = cam ? await grabLiveFrame(cam.stream_id) : false;
      if (!live) {
        try {
          const page = await api.events({ camera_id: id }, 1, 20);
          const withSnap = page.items.find((e) => e.snapshot_url);
          if (withSnap?.snapshot_url) setImageUrl(withSnap.snapshot_url);
        } catch {
          /* no snapshot yet */
        }
      }
    });
  }, [id]);

  const toImageCoords = (e: { clientX: number; clientY: number }): Pt => {
    const rect = svgRef.current!.getBoundingClientRect();
    return [
      Math.round(((e.clientX - rect.left) / rect.width) * imgSize[0]),
      Math.round(((e.clientY - rect.top) / rect.height) * imgSize[1]),
    ];
  };

  const beginDrag = (
    e: React.PointerEvent,
    type: "line" | "polygon" | "homography",
    idx: number,
    vertex: number | null,
  ) => {
    if (tool !== "select") return;
    e.stopPropagation();
    svgRef.current?.setPointerCapture?.(e.pointerId);
    dragMovedRef.current = false;
    snapshot();
    const pts0: Pt[] =
      type === "line"
        ? (lines[idx].points as Pt[])
        : type === "polygon"
          ? (polygons[idx].points as Pt[])
          : homographySrc;
    setDrag({ type, idx, vertex, origin: toImageCoords(e), snapshot: pts0 });
  };

  const onSvgPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const p = toImageCoords(e);
    if (!drag) {
      if (tool === "polygon" || tool === "line") setCursorPt(p);
      return;
    }
    const dx = p[0] - drag.origin[0];
    const dy = p[1] - drag.origin[1];
    if (Math.abs(dx) + Math.abs(dy) > 4) dragMovedRef.current = true;
    if (drag.type === "homography") {
      setHomographySrc((pts) =>
        pts.map((pt, i) => (drag.vertex === i ? [drag.snapshot[i][0] + dx, drag.snapshot[i][1] + dy] : pt)),
      );
    } else if (drag.type === "line") {
      setLines((ls) =>
        ls.map((l, i) =>
          i === drag.idx
            ? {
                ...l,
                points: l.points.map((pt, vi) =>
                  drag.vertex === null || drag.vertex === vi
                    ? [drag.snapshot[vi][0] + dx, drag.snapshot[vi][1] + dy]
                    : pt,
                ) as RoiLine["points"],
              }
            : l,
        ),
      );
    } else {
      setPolygons((ps) =>
        ps.map((poly, i) =>
          i === drag.idx
            ? {
                ...poly,
                points: poly.points.map((pt, vi) =>
                  drag.vertex === null || drag.vertex === vi
                    ? [drag.snapshot[vi][0] + dx, drag.snapshot[vi][1] + dy]
                    : pt,
                ) as RoiPolygon["points"],
              }
            : poly,
        ),
      );
    }
  };

  const onCanvasClick = (e: React.MouseEvent<SVGSVGElement>) => {
    if (dragMovedRef.current) {
      dragMovedRef.current = false;
      return;
    }
    const p = toImageCoords(e);
    if (tool === "polygon") {
      // cerrar si el clic cae cerca del primer vértice
      if (draft.length >= 3) {
        const [fx, fy] = draft[0];
        if (Math.hypot(p[0] - fx, p[1] - fy) < 18) {
          closePolygonDraft();
          return;
        }
      }
      setDraft((d) => [...d, p]);
    } else if (tool === "line") {
      const next = [...draft, p];
      setDraft(next);
      if (next.length === 2) {
        snapshot();
        setLines((ls) => [...ls, { id: `L${ls.length + 1}`, points: next }]);
        setSelected({ type: "line", idx: lines.length });
        setTool("select");
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
        snapshot();
        setPolygons((ps) => ps.filter((_, i) => i !== pIdx));
        return;
      }
      const lIdx = lines.findIndex((l) => hitTestLine(p, l, 12));
      if (lIdx >= 0) {
        snapshot();
        setLines((ls) => ls.filter((_, i) => i !== lIdx));
      }
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

  const onSvgPointerUp = () => {
    setDrag(null);
    setCursorPt(null);
  };

  const closePolygonDraft = () => {
    if (draft.length >= 3) {
      snapshot();
      setPolygons((ps) => [
        ...ps,
        {
          id: `lane-${ps.length + 1}`,
          points: draft,
          kind: camera?.analytics_profile === "people" ? "counting" : "lane",
          rules: [camera?.analytics_profile === "people" ? "occupancy" : "stopped"],
        },
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

  const cameraDomain = camera?.analytics_profile ?? null;

  return (
    <div className="flex h-full">
      <div className="flex min-w-0 flex-1 flex-col p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h1 className="font-display text-lg font-semibold">
            ROI — {camera?.name ?? "…"}
          </h1>
          {camera && (
            <select
              value={cameraDomain ?? "traffic"}
              onChange={async (e) => {
                const nd = e.target.value as "traffic" | "people";
                const patch = { analytics_profile: nd };
                await api.updateCamera(camera.id, patch);
                setCamera({ ...camera, ...patch } as Camera);
              }}
              className="rounded-md border border-line bg-panel px-2 py-1 text-xs"
            >
              <option value="traffic">🚗 Tráfico</option>
              <option value="people">🧍 Personas</option>
            </select>
          )}
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
            <button
              type="button"
              onClick={undo}
              disabled={history.length === 0}
              title="Deshacer (Ctrl+Z)"
              className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-xs text-mut transition-colors hover:text-ink disabled:opacity-40"
            >
              <Undo2 size={14} /> Deshacer{history.length ? ` (${history.length})` : ""}
            </button>
            <button
              type="button"
              onClick={() => camera && grabLiveFrame(camera.stream_id)}
              className="flex items-center gap-1.5 rounded-md border border-brand px-2.5 py-1.5 text-xs text-ink transition-colors hover:bg-brand/15"
              title="Capturar frame actual de la cámara"
            >
              <RefreshCw size={14} /> Frame en vivo
            </button>
            {whepUrl && (
              <button
                type="button"
                onClick={() => {
                  setLiveMode((v) => !v);
                  setFrozen(false);
                }}
                className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs transition-colors ${
                  liveMode
                    ? "border-brand bg-brand/15 text-ink"
                    : "border-line text-mut hover:text-ink"
                }`}
                title="Ver y dibujar sobre el video en vivo"
              >
                <Video size={14} /> {liveMode ? "En vivo" : "Editar en vivo"}
              </button>
            )}
            {liveMode && (
              <button
                type="button"
                onClick={toggleFreeze}
                className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-xs text-mut hover:text-ink"
                title="Congelar video para dibujar tranquilo"
              >
                {frozen ? <Play size={14} /> : <Pause size={14} />} {frozen ? "Reanudar" : "Congelar"}
              </button>
            )}
            <label className="flex cursor-pointer items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-xs text-mut hover:text-ink" title="Subir imagen manualmente">
              <ImageUp size={14} /> Subir
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

        <div
          ref={stageRef}
          className="relative min-h-0 flex-1 overflow-hidden rounded-lg border border-line bg-panel"
        >
          {(imageUrl || liveMode) && boxSize ? (
            <div className="absolute inset-0 grid place-items-center">
              <div
                className="relative"
                style={{ width: `${boxSize.w}px`, height: `${boxSize.h}px` }}
              >
                {liveMode ? (
                  <video
                    ref={videoRef}
                    muted
                    playsInline
                    className="absolute inset-0 h-full w-full object-fill"
                  />
                ) : (
                  <img
                    src={imageUrl ?? ""}
                    alt="frame"
                    draggable={false}
                    className="absolute inset-0 h-full w-full select-none object-fill"
                    onLoad={(e) =>
                      setImgSize([
                        e.currentTarget.naturalWidth || 1280,
                        e.currentTarget.naturalHeight || 720,
                      ])
                    }
                  />
                )}
                <RoiCanvas
                  cursorPt={cursorPt}
                  svgRef={svgRef}
                  imgSize={imgSize}
                  tool={tool}
                  polygons={polygons}
                  lines={lines}
                  homographySrc={homographySrc}
                  draft={draft}
                  selected={selected}
                  onCanvasClick={onCanvasClick}
                  onDoubleClick={tool === "polygon" ? closePolygonDraft : undefined}
                  onPointerMove={onSvgPointerMove}
                  onPointerUp={onSvgPointerUp}
                  onPointerLeave={onSvgPointerUp}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setDraft((d) => d.slice(0, -1));
                  }}
                  beginDrag={beginDrag}
                />
              </div>
            </div>
          ) : (
            <div className="absolute inset-0 grid place-items-center text-center">
              <p className="max-w-xs text-sm text-dim">
                Sin frame de fondo. Usa «Frame en vivo» para capturar la imagen actual de la
                cámara, o sube una imagen manualmente.
              </p>
            </div>
          )}
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
