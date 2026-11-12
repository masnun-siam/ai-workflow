import { http } from "../api/http";
import type { PushSubscription as Sub } from "../api/types";

export type PushState = "unsupported" | "denied" | "off" | "on";

export const pushSupported = (): boolean =>
  typeof navigator !== "undefined" && "serviceWorker" in navigator && typeof Notification !== "undefined" && "PushManager" in globalThis;

/** Registers the service worker (needed for push and for installing the PWA). Silent when unavailable (plain http, tests). */
export async function registerSW(): Promise<void> {
  try {
    if (typeof navigator !== "undefined" && "serviceWorker" in navigator) await navigator.serviceWorker.register("/sw.js");
  } catch { /* insecure origin or blocked: the UI works without it */ }
}

function b64ToBytes(s: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export async function pushState(): Promise<PushState> {
  if (!pushSupported()) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  try {
    const reg = await navigator.serviceWorker.getRegistration();
    return (await reg?.pushManager.getSubscription()) ? "on" : "off";
  } catch { return "off"; }
}

export async function subscribePush(): Promise<void> {
  if (!pushSupported()) throw new Error("push is not supported here (needs https or localhost)");
  if ((await Notification.requestPermission()) !== "granted") throw new Error("notification permission was not granted");
  await registerSW();
  const reg = await navigator.serviceWorker.ready;
  const { public_key } = await http.get<{ public_key: string }>("/api/push/key");
  const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(public_key) }));
  const j = sub.toJSON() as { endpoint?: string; keys?: Sub["keys"] };
  await http.send("POST", "/api/push/subscription", { endpoint: j.endpoint, keys: j.keys });
}

export async function unsubscribePush(): Promise<void> {
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = await reg?.pushManager.getSubscription();
  if (!sub) return;
  await http.send("DELETE", "/api/push/subscription", { endpoint: sub.endpoint });
  await sub.unsubscribe();
}
