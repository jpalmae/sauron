import { CameraOff, Maximize2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Camera } from "../lib/api";

/**
 * WHEP player (MediaMTX-compatible). Falls back to an offline tile when the
 * stream gateway is unreachable or no WHEP endpoint is configured.
 */
function WhepTile({ camera }: { camera: Camera }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<"connecting" | "live" | "offline">("connecting");

  useEffect(() => {
    const pc = new RTCPeerConnection();
    let cancelled = false;

    async function connect() {
      try {
        pc.addTransceiver("video", { direction: "recvonly" });
        pc.addTransceiver("audio", { direction: "recvonly" });
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        const resp = await fetch(`/whep/${camera.stream_id}`, {
          method: "POST",
          headers: { "Content-Type": "application/sdp" },
          body: offer.sdp,
        });
        if (!resp.ok) throw new Error(String(resp.status));
        await pc.setRemoteDescription({ type: "answer", sdp: await resp.text() });
        if (!cancelled) setState("live");
      } catch {
        if (!cancelled) setState("offline");
      }
    }

    pc.ontrack = (e) => {
      if (videoRef.current) videoRef.current.srcObject = e.streams[0];
    };
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
        setState("offline");
      }
    };
    void connect();
    return () => {
      cancelled = true;
      pc.close();
    };
  }, [camera.stream_id]);

  return (
    <div className="group relative overflow-hidden rounded-lg border border-line bg-panel">
      {state === "live" ? (
        <video ref={videoRef} autoPlay muted playsInline className="aspect-video w-full object-cover" />
      ) : (
        <div className="grid aspect-video w-full place-items-center bg-[repeating-linear-gradient(45deg,transparent,transparent_10px,var(--color-panel)_10px,var(--color-panel)_20px)]">
          <div className="flex flex-col items-center gap-2 text-dim">
            <CameraOff size={28} strokeWidth={1.5} />
            <span className="font-mono text-[11px]">
              {state === "connecting" ? "conectando…" : "sin señal"}
            </span>
          </div>
        </div>
      )}
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
        <WhepTile key={cam.id} camera={cam} />
      ))}
    </div>
  );
}
