import { useCallback, useEffect, useState } from "react";
import AlertPanel, { type AlertEntry } from "../components/AlertPanel";
import CameraGrid from "../components/CameraGrid";
import OccupancyWidget from "../components/OccupancyWidget";
import { api, type Camera } from "../lib/api";
import { playAlertPing } from "../lib/audio";
import { filterCamerasByDomain, filterEventsByDomain, type Domain, isPeopleEvent, isTrafficEvent } from "../lib/domain";
import { useAlertsWs, type WsAlert } from "../lib/ws";

const MAX_ALERTS = 60;

export default function LivePage({
  onWsState,
  domain,
}: {
  onWsState: (connected: boolean) => void;
  domain?: Domain;
}) {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [alerts, setAlerts] = useState<AlertEntry[]>([]);
  const [soundOn, setSoundOn] = useState(false);

  const filteredCameras = domain ? filterCamerasByDomain(cameras, domain) : cameras;
  const filteredAlerts = domain
    ? alerts.filter((a) => (domain === "traffic" ? isTrafficEvent(a) : isPeopleEvent(a)))
    : alerts;

  useEffect(() => {
    api.cameras().then(setCameras).catch(console.error);
    api
      .events({ priority: "critical" }, 1, 20)
      .then((page) => setAlerts(domain ? filterEventsByDomain(page.items, domain) : page.items))
      .catch(console.error);
  }, [domain]);

  const onAlert = useCallback(
    (a: WsAlert) => {
      if (domain) {
        const isRelevant = domain === "traffic" ? isTrafficEvent(a as any) : isPeopleEvent(a as any);
        if (!isRelevant) return;
      }
      setAlerts((prev) =>
        [
          {
            ...a,
            timestamp: a.timestamp,
            snapshot_url: null,
            clip_url: null,
            acknowledged_at: null,
            acknowledged_by: null,
            live: true,
          } as AlertEntry,
          ...prev,
        ].slice(0, MAX_ALERTS),
      );
      if (a.priority === "critical" && soundOn) playAlertPing("critical");
    },
    [soundOn, domain],
  );

  const connected = useAlertsWs(onAlert);
  useEffect(() => onWsState(connected), [connected, onWsState]);

  const onAck = (eventId: string) => {
    api
      .ackEvent(eventId)
      .then((updated) => {
        setAlerts((prev) =>
          prev.map((a) =>
            a.event_id === eventId
              ? { ...a, acknowledged_at: updated.acknowledged_at, acknowledged_by: updated.acknowledged_by }
              : a,
          ),
        );
      })
      .catch(console.error);
  };

  return (
    <div className="flex h-full">
      <div className="min-w-0 flex-1 overflow-y-auto p-4">
        {domain === "people" && filteredCameras.length > 0 && (
          <div className="mb-3 grid gap-3 lg:grid-cols-2">
            {filteredCameras.map((c) => (
              <OccupancyWidget key={c.id} cameraId={c.id} name={c.name} />
            ))}
          </div>
        )}
        <CameraGrid cameras={filteredCameras} />
        {filteredCameras.length === 0 && (
          <p className="mt-6 text-center text-sm text-dim">
            Sin cámaras de {domain === "traffic" ? "tráfico" : "personas"} configuradas.{" "}
            <span className="text-mut">Añádelas en Cámaras.</span>
          </p>
        )}
      </div>
      <div className="w-80 shrink-0 xl:w-96">
        <AlertPanel
          alerts={filteredAlerts}
          soundOn={soundOn}
          onToggleSound={() => setSoundOn((s) => !s)}
          onAck={onAck}
        />
      </div>
    </div>
  );
}
