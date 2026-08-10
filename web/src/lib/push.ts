import { api, auth } from "./api";

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export function pushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!pushSupported()) return null;
  return navigator.serviceWorker.register("/sw.js");
}

/** Ask permission and subscribe to alert pushes. Returns the new state. */
export async function subscribeToPushes(): Promise<"subscribed" | "denied" | "unsupported"> {
  const reg = await registerServiceWorker();
  if (!reg) return "unsupported";
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return "denied";

  const { public_key } = await api.pushPublicKey();
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(public_key) as BufferSource,
  });
  const json = sub.toJSON() as { endpoint: string; keys: { p256dh: string; auth: string } };
  await api.pushSubscribe(json.endpoint, json.keys);
  return "subscribed";
}

export function isSubscribed(): boolean {
  return (
    pushSupported() &&
    Notification.permission === "granted" &&
    Boolean(auth.token())
  );
}
