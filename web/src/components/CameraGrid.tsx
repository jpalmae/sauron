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

function LiveTile({ camera }: { camera: Camera }) {
  const [source, setSource] = useState<{ kind: string; url: string } | null>(null);
  const [state, setState] = useState<TileState>("connecting");
  const [analyticsState, setAnalyticsState] = useState<AnalyticsState>("connecting");

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
  }, [camera.stream_id]);

  return (
    <div className="group relative overflow-hidden rounded-lg border border-line bg-panel">
      <DetectionsOverlay cameraId={camera.id} onState={setAnalyticsState} />
      {source?.kind === "hls" && <HlsVideo url={source.url} onState={setState} />}
      {source?.kind === "whep" && <WhepVideo url={source.url} onState={setState} />}
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

export default function CameraGrid({ cameras }: { cameras: Camera[] }) {
  const active = cameras.filter((c) => c.is_active);
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
    <div
      className={`grid gap-3 ${
        active.length === 1
          ? "grid-cols-1"
          : active.length <= 4
            ? "grid-cols-1 lg:grid-cols-2"
            : "grid-cols-1 md:grid-cols-2 xl:grid-cols-3"
      }`}
    >
      {active.map((cam) => (
        <LiveTile key={cam.id} camera={cam} />
      ))}
    </div>
  );
}
