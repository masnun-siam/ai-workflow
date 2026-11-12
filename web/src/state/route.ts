import { signal } from "@preact/signals";

export const SCREENS = [
  ["river", "River"],
  ["inbox", "Inbox"],
  ["runs", "Runs"],
  ["releases", "Releases"],
  ["ops", "Ops"],
  ["me", "Me"],
  ["settings", "Settings"],
] as const;
export type ScreenId = (typeof SCREENS)[number][0];
export type Route = { screen: ScreenId | "prd"; id?: string; query: Record<string, string> };

const IDS = new Set<string>(SCREENS.map((s) => s[0]));

/** `#/river`, `#/sessions/<id>` (Runs, full page), `#/prd?repo=..&path=..`. Unknown -> river. */
export function parseHash(hash: string): Route {
  const h = hash.replace(/^#\/?/, "");
  const [pathPart = "", qs = ""] = h.split("?");
  const query: Record<string, string> = {};
  for (const [k, v] of new URLSearchParams(qs)) query[k] = v;
  const seg = pathPart.split("/").filter(Boolean);
  if (seg[0] === "sessions" && seg[1]) return { screen: "runs", id: decodeURIComponent(seg[1]), query };
  if (seg[0] === "prd") return { screen: "prd", query };
  if (seg[0] && IDS.has(seg[0])) return { screen: seg[0] as ScreenId, query };
  return { screen: "river", query };
}
export function hashFor(screen: ScreenId): string {
  return `#/${screen}`;
}

export const route = signal<Route>(parseHash(globalThis.location?.hash ?? ""));

export function nav(hash: string): void {
  if (globalThis.location) globalThis.location.hash = hash;
  else route.value = parseHash(hash);
}
export function startRouter(): () => void {
  const on = () => (route.value = parseHash(location.hash));
  addEventListener("hashchange", on);
  on();
  return () => removeEventListener("hashchange", on);
}
export const goScreen = (s: ScreenId) => nav(hashFor(s));
