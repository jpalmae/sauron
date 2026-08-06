import { useCallback, useEffect, useState } from "react";
import AlertPanel, { type AlertEntry } from "../components/AlertPanel";
import CameraGrid from "../components/CameraGrid";
import { api, type Camera } from "../lib/api";
import { playAlertPing } from "../lib/audio";
import { useAlertsWs, type WsAlert } from "../lib/ws";

const MAX_ALERTS = 60;

export default function LivePage({
  onWsState,
}: {
  onWsState: (connected: boolean) => void;
}) {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [alerts, setAlerts] = useState<AlertEntry[]>([]);
  const [soundOn, setSoundOn] = useState(false);

  useEffect(() => {
    api.cameras().then(setCameras).catch(console.error);
    api
      .events({ priority: "critical" }, 1, 10)
      .then((page) => setAlerts(page.items))
      .catch(console.error);
  }, []);

  const onAlert = useCallback(
    (a: WsAlert) => {
      setAlerts((prev) =>
        [
          {
            ...a,
            timestamp: a.timestamp,
            snapshot_url: null,
            clip_url: null,
            live: true,
          } as AlertEntry,
          ...prev,
        ].slice(0, MAX_ALERTS),
      );
      if (a.priority === "critical" && soundOn) playAlertPing("critical");
    },
    [soundOn],
  );

  const connected = useAlertsWs(onAlert);
  useEffect(() => onWsState(connected), [connected, onWsState]);

  return (
    <div className="flex h-full">
      <div className="min-w-0 flex-1 overflow-y-auto p-4">
        <CameraGrid cameras={cameras} />
      </div>
      <div className="w-80 shrink-0 xl:w-96">
        <AlertPanel
          alerts={alerts}
          soundOn={soundOn}
          onToggleSound={() => setSoundOn((s) => !s)}
        />
      </div>
    </div>
  );
}
