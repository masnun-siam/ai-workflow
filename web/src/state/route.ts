import { signal } from "@preact/signals";

/** The rail, in order. Number keys 1-9 go to the first nine, 0 to Settings. */
export const SCREENS = [
  ["inbox", "Inbox"],
  ["features", "Features"],
  ["changes", "Small changes"],
  ["dispatches", "Dispatches"],
  ["activity", "Activity"],
  ["river", "River"],
  ["releases", "Releases"],
  ["ops", "Ops"],
  ["me", "Me"],
  ["settings", "Settings"],
] as const;
export type ScreenId = (typeof SCREENS)[number][0];
export type Route = { screen: ScreenId | "prd" | "onboarding"; id?: string; query: Record<string, string> };

const IDS = new Set<string>(SCREENS.map((s) => s[0]));
/** Old hashes that moved: the Runs screen split into Dispatches and Activity. */
const ALIASES: Record<string, ScreenId> = { runs: "activity", issues: "changes" };

/** `#/inbox?only=o/r`, `#/sessions/<id>` (Activity, full page), `#/features/<slug>?product=o/r` (feature page), `#/prd?repo=..&path=..`, `#/onboarding`. Unknown or malformed -> inbox. */
export function parseHash(hash: string): Route {
  return parseKnown(hash) ?? { screen: "inbox", query: {} };
}

/** The route for a hash, or null when no page matches it or an id will not decode. */
function parseKnown(hash: string): Route | null {
  try { return parseSegments(hash); } catch { return null; }
}

function parseSegments(hash: string): Route | null {
  const h = hash.replace(/^#\/?/, "");
  const [pathPart = "", qs = ""] = h.split("?");
  const query: Record<string, string> = {};
  for (const [k, v] of new URLSearchParams(qs)) query[k] = v;
  const seg = pathPart.split("/").filter(Boolean);
  if (seg[0] === "sessions" && seg[1]) return { screen: "activity", id: decodeURIComponent(seg[1]), query };
  if (seg[0] === "prd") return { screen: "prd", query };
  if (seg[0] === "onboarding") return { screen: "onboarding", query };
  if ((seg[0] === "features" || seg[0] === "dispatches") && seg[1]) return { screen: seg[0], id: decodeURIComponent(seg[1]), query };
  if (seg[0] && IDS.has(seg[0])) return { screen: seg[0] as ScreenId, query };
  if (seg[0] && ALIASES[seg[0]]) return { screen: ALIASES[seg[0]]!, query };
  return seg[0] ? null : { screen: "inbox", query };
}

/** A query string with `key` set (dropped for ""), keeping the others and a readable slash. */
export function withParam(query: Record<string, string>, key: string, value: string): string {
  const sp = new URLSearchParams(query);
  if (value) sp.set(key, value);
  else sp.delete(key);
  const s = sp.toString().replace(/%2F/gi, "/");
  return s ? `?${s}` : "";
}

/** The hash for a screen. `only` (the page's repo filter) carries over between list screens. */
export function hashFor(screen: ScreenId, query: Record<string, string> = {}): string {
  return `#/${screen}${withParam({}, "only", query.only ?? "")}`;
}

export const route = signal<Route>(parseHash(globalThis.location?.hash ?? ""));

export function nav(hash: string, replace = false): void {
  if (!globalThis.location) { route.value = parseHash(hash); return; }
  if (replace) { history.replaceState(null, "", hash); route.value = parseHash(hash); }
  else globalThis.location.hash = hash;
}
/** Set one query param on the current screen. */
export function setParam(key: string, value: string, replace = false): void {
  const h = (globalThis.location?.hash ?? "").split("?")[0] || `#/${route.peek().screen}`;
  nav(`${h}${withParam(route.peek().query, key, value)}`, replace);
}
/** True once the user moved inside the app, so history.back() stays in setu. */
export let movedInApp = false;
/** Back to the previous in-app screen, or `fallback` when the page was opened directly. */
export function goBack(fallback: ScreenId): void {
  if (movedInApp) history.back();
  else goScreen(fallback);
}
export function startRouter(): () => void {
  let first = true;
  const on = () => {
    if (!first) movedInApp = true;
    first = false;
    if (!parseKnown(location.hash)) { nav("#/inbox", true); return; } // an unknown or malformed hash becomes the inbox
    route.value = parseHash(location.hash);
  };
  addEventListener("hashchange", on);
  on();
  return () => removeEventListener("hashchange", on);
}
export const goScreen = (s: ScreenId) => nav(hashFor(s, route.peek().query));
