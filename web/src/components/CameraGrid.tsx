import Hls from "hls.js";
import { CameraOff, Maximize2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, auth, type Camera } from "../lib/api";
import DetectionsOverlay, { type AnalyticsState } from "./DetectionsOverlay";

type TileState = "connecting" | "live" | "offline";

function HlsVideo({ url, onState }: { url: string; onState: (s: TileState) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let hls: Hls | null = null;
    // HLS players fetch without Authorization header -> carry the JWT in the URL
    const token = auth.token();
    const authedUrl = token
      ? `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`
      : url;

    if (Hls.isSupported()) {
      hls = new Hls({ liveSyncDurationCount: 3 });
      hls.loadSource(authedUrl);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        void video.play();
        onState("live");
      });
      hls.on(Hls.Events.ERROR, (_, data) => {
        if (data.fatal) onState("offline");
      });
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = authedUrl;
      video.onloadedmetadata = () => {
        void video.play();
        onState("live");
      };
      video.onerror = () => onState("offline");
    } else {
      onState("offline");
    }
    return () => hls?.destroy();
  }, [url, onState]);

  return <video ref={videoRef} muted playsInline className="aspect-video w-full object-cover" />;
}

function WhepVideo({ url, onState }: { url: string; onState: (s: TileState) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const pc = new RTCPeerConnection();
    let cancelled = false;
    let disconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const markLive = () => {
      if (!cancelled) onState("live");
    };

    async function connect() {
      try {
        pc.addTransceiver("video", { direction: "recvonly" });
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        const resp = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/sdp" },
          body: offer.sdp,
        });
        if (!resp.ok) throw new Error(String(resp.status));
        await pc.setRemoteDescription({ type: "answer", sdp: await resp.text() });
      } catch {
        if (!cancelled) onState("offline");
      }
    }

    pc.ontrack = (e) => {
      if (videoRef.current) {
        videoRef.current.srcObject = e.streams[0];
        videoRef.current.onplaying = markLive;
      }
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "connected") {
        if (disconnectTimer) clearTimeout(disconnectTimer);
        markLive();
      } else if (pc.connectionState === "failed" || pc.connectionState === "closed") {
        onState("offline");
      } else if (pc.connectionState === "disconnected") {
        if (disconnectTimer) clearTimeout(disconnectTimer);
        disconnectTimer = setTimeout(() => {
          if (!cancelled && pc.connectionState === "disconnected") onState("offline");
        }, 3000);
      }
    };
    void connect();
    return () => {
      cancelled = true;
      if (disconnectTimer) clearTimeout(disconnectTimer);
      pc.close();
    };
  }, [url, onState]);

  return <video ref={videoRef} autoPlay muted playsInline className="aspect-video w-full object-cover" />;
}

const OFFLINE_RETRY_MS = 20000;

function LiveTile({
  camera,
  onOpen,
  onStateChange,
}: {
  camera: Camera;
  onOpen?: (c: Camera) => void;
  onStateChange?: (id: string, s: TileState) => void;
}) {
  const [source, setSource] = useState<{ kind: string; url: string } | null>(null);
  const [stateRaw, setStateRaw] = useState<TileState>("connecting");
  const [analyticsState, setAnalyticsState] = useState<AnalyticsState>("connecting");
  const [retry, setRetry] = useState(0);

  const setState = (s: TileState) => {
    setStateRaw(s);
    onStateChange?.(camera.id, s);
  };
  const state = stateRaw;

  // reintento automatico: la camara vuelve a intentar conectarse cada 20s
  useEffect(() => {
    if (state !== "offline") return;
    const t = setTimeout(() => setRetry((r) => r + 1), OFFLINE_RETRY_MS);
    return () => clearTimeout(t);
  }, [state, retry]);

  useEffect(() => {
    let alive = true;
    api
      .liveUrl(camera.stream_id)
      .then((s) => {
        if (!alive) return;
        if (s.kind === "none") setState("offline");
        setSource(s);
      })
      .catch(() => alive && setState("offline"));
    return () => {
      alive = false;
    };
  }, [camera.stream_id, retry]);

  // offline: recuadro compacto; el player queda montado oculto reintentando
  if (state === "offline") {
    return (
      <div
        className="flex cursor-pointer items-center gap-2 rounded-lg border border-line/60 bg-panel/60 px-3 py-2.5 transition-colors hover:border-brand/40"
        onClick={() => onOpen?.(camera)}
        role="status"
      >
        <CameraOff size={14} className="shrink-0 text-crit" strokeWidth={1.5} />
        <span className="truncate font-display text-xs text-mut">{camera.name}</span>
        <span className="ml-auto shrink-0 font-mono text-[10px] text-crit">offline</span>
        <div className="hidden">
          {source?.kind === "hls" && <HlsVideo key={retry} url={source.url} onState={setState} />}
          {source?.kind === "whep" && <WhepVideo key={retry} url={source.url} onState={setState} />}
        </div>
      </div>
    );
  }

  return (
    <div
      className="group relative cursor-pointer overflow-hidden rounded-lg border border-line bg-panel transition-colors hover:border-brand/50"
      onClick={() => onOpen?.(camera)}
    >
      <DetectionsOverlay cameraId={camera.id} onState={setAnalyticsState} profile={camera.analytics_profile} />
      {source?.kind === "hls" && <HlsVideo key={retry} url={source.url} onState={setState} />}
      {source?.kind === "whep" && <WhepVideo key={retry} url={source.url} onState={setState} />}
      {(!source || state !== "live") && (
        <div className="absolute inset-0 grid place-items-center bg-[repeating-linear-gradient(45deg,transparent,transparent_10px,var(--color-panel)_10px,var(--color-panel)_20px)]">
          <div className="flex flex-col items-center gap-2 text-dim">
            <CameraOff size={28} strokeWidth={1.5} />
            <span className="font-mono text-[11px]">
              {state === "connecting" ? "conectando…" : "sin señal"}
            </span>
          </div>
        </div>
      )}
      {!source && <div className="aspect-video w-full" />}
      <div className="absolute inset-x-0 top-0 flex items-center justify-between bg-gradient-to-b from-base/80 to-transparent px-3 py-2">
        <div className="flex items-center gap-2">
          <span
            className={`h-1.5 w-1.5 rounded-full ${state === "live" ? "bg-info" : "bg-crit"}`}
          />
          <span className="font-display text-xs font-medium text-ink">{camera.name}</span>
        </div>
        <span className="font-mono text-[10px] text-mut opacity-0 transition-opacity group-hover:opacity-100">
          <Maximize2 size={12} className="inline" /> {camera.stream_id}
        </span>
      </div>
      <div
        className={`absolute bottom-2 right-2 z-20 rounded border px-2 py-1 font-mono text-[9px] backdrop-blur-sm ${
          analyticsState === "live"
            ? "border-info/40 bg-info/15 text-info"
            : analyticsState === "connecting"
              ? "border-line bg-base/70 text-mut"
              : "border-warn/40 bg-warn/15 text-warn"
        }`}
        role="status"
      >
        {analyticsState === "live"
          ? "ANALÍTICA ACTIVA"
          : analyticsState === "connecting"
            ? "ANALÍTICA CONECTANDO"
            : analyticsState === "stale"
              ? "ANALÍTICA SIN FRAMES"
              : "ANALÍTICA NO DISPONIBLE"}
      </div>
    </div>
  );
}

const DEMOTE_AFTER_MS = 15000;

export default function CameraGrid({ cameras }: { cameras: Camera[] }) {
  const [openCam, setOpenCam] = useState<Camera | null>(null);
  const [states, setStates] = useState<Record<string, TileState>>({});
  const [offlineSince, setOfflineSince] = useState<Record<string, number>>({});
  const [, setTick] = useState(0);
  // re-evaluar la democion diferida aunque no cambie ningun estado
  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 5000);
    return () => clearInterval(t);
  }, []);
  const onStateChange = (id: string, s: TileState) => {
    setStates((prev) => (prev[id] === s ? prev : { ...prev, [id]: s }));
    setOfflineSince((prev) => {
      if (s !== "offline") {
        if (!prev[id]) return prev;
        const next = { ...prev };
        delete next[id];
        return next;
      }
      return prev[id] ? prev : { ...prev, [id]: Date.now() };
    });
  };
  const active = cameras.filter((c) => c.is_active);
  // histeresis: solo baja al fondo si lleva 15 s caida (evita pestañeo
  // por microcortes de WebRTC); al recuperar sube de inmediato
  const demoted = (id: string) =>
    states[id] === "offline" && Date.now() - (offlineSince[id] ?? Date.now()) >= DEMOTE_AFTER_MS;
  const online = active.filter((c) => !demoted(c.id));
  const offline = active.filter((c) => demoted(c.id));
  if (active.length === 0) {
    return (
      <div className="grid h-full place-items-center">
        <div className="max-w-sm text-center">
          <CameraOff size={32} className="mx-auto text-dim" strokeWidth={1.5} />
          <p className="mt-3 font-display text-lg">Sin cámaras activas</p>
          <p className="mt-1 text-sm text-mut">
            Registra tu primera cámara en la sección Cámaras para comenzar el monitoreo.
          </p>
        </div>
      </div>
    );
  }
  return (
    <div>
      <div
        className={`grid gap-3 ${
          online.length === 1
            ? "grid-cols-1"
            : online.length <= 4
              ? "grid-cols-1 lg:grid-cols-2"
              : "grid-cols-1 md:grid-cols-2 xl:grid-cols-3"
        }`}
      >
        {online.map((cam) => (
          <LiveTile key={cam.id} camera={cam} onOpen={setOpenCam} onStateChange={onStateChange} />
        ))}
      </div>
      {offline.length > 0 && (
        <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {offline.map((cam) => (
            <LiveTile key={cam.id} camera={cam} onOpen={setOpenCam} onStateChange={onStateChange} />
          ))}
        </div>
      )}
      {openCam && (
        <CameraModal camera={openCam} onClose={() => setOpenCam(null)} />
      )}
    </div>
  );
}

function CameraModal({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  const [source, setSource] = useState<{ kind: string; url: string } | null>(null);
  const [state, setState] = useState<TileState>("connecting");

  useEffect(() => {
    let alive = true;
    api
      .liveUrl(camera.stream_id)
      .then((s) => {
        if (!alive) return;
        if (s.kind === "none") setState("offline");
        setSource(s);
      })
      .catch(() => alive && setState("offline"));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      alive = false;
      window.removeEventListener("keydown", onKey);
    };
  }, [camera.stream_id, onClose]);

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/80 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-5xl overflow-hidden rounded-xl border border-line bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${state === "live" ? "bg-info" : "bg-crit"}`} />
            <span className="font-display text-sm font-medium text-ink">{camera.name}</span>
            <span className="font-mono text-[10px] text-mut">{camera.stream_id}</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-line px-2 py-1 text-xs text-mut hover:text-ink"
          >
            Cerrar (Esc)
          </button>
        </div>
        <div className="relative aspect-video w-full bg-black">
          {source?.kind === "hls" && <HlsVideo url={source.url} onState={setState} />}
          {source?.kind === "whep" && <WhepVideo url={source.url} onState={setState} />}
          {(!source || state !== "live") && (
            <div className="absolute inset-0 grid place-items-center">
              <span className="font-mono text-xs text-dim">
                {state === "connecting" ? "conectando…" : "sin señal"}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
