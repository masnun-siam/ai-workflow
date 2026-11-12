/** API.md section 6: which resources the UI refetches for each SSE event. Pure, so it is unit-tested. */
import type { Topic } from "../api/sse";

export type LoadKey =
  | "status" | "river" | "inbox" | "sessions" | "session" | "stream" | "releases" | "ops" | "me"
  | "settings" | "notify" | "review" | "blubird" | "products" | "repos" | "dispatches" | "coordinators"
  | "grinds" | "panels" | "registry" | "features";

export type View = { screen: string; sessionId?: string; tab?: string };

/** What the current view shows, i.e. what a `hello` (connect or resync) refetches. Status and the inbox badge are always live. */
export function visibleKeys(v: View): LoadKey[] {
  // The rail counts (needs you, dispatching, running) and the repo switcher are always live.
  const base: LoadKey[] = ["status", "inbox", "products", "repos", "sessions", "dispatches"];
  switch (v.screen) {
    case "river": return [...base, "river"];
    case "inbox": return base;
    case "features": return [...base, "features", "panels"];
    case "changes": return [...base, "river"];
    case "dispatches": return base;
    case "activity": {
      const k: LoadKey[] = [...base];
      if (v.sessionId) k.push("session", "stream");
      if (v.tab === "coordinators") k.push("coordinators");
      if (v.tab === "grinds") k.push("grinds");
      if (v.tab === "panels") k.push("panels");
      return k;
    }
    case "onboarding": return [...base, "settings"];
    case "releases": return [...base, "releases"];
    case "ops": return [...base, "ops"];
    case "me": return [...base, "me"];
    case "settings": return [...base, "settings", "notify", "review", "blubird", "repos"];
    default: return base;
  }
}

type P = Record<string, unknown> | null;

/** Keys to reload for one event, already limited to what the view shows. `toast` reloads nothing. */
export function refetchFor(topic: Topic, payload: unknown, v: View): LoadKey[] {
  const p = (payload && typeof payload === "object" ? payload : null) as P;
  const vis = new Set(visibleKeys(v));
  const out = new Set<LoadKey>();
  const add = (...k: LoadKey[]) => k.forEach((x) => vis.has(x) && out.add(x));
  switch (topic) {
    case "hello": visibleKeys(v).forEach((k) => out.add(k)); break;
    case "sessions": {
      add("sessions", "river", "me", "features");
      if (v.sessionId && p?.id === v.sessionId) {
        add("session");
        if (p.change === "stream" || p.change === "record") add("stream");
      }
      break;
    }
    case "inbox": add("inbox"); break;
    case "products": {
      switch (p?.kind) {
        case "snapshot": add("river", "ops", "releases", "products", "features"); break;
        case "registry": add("products", "repos", "river", "ops", "releases"); break;
        case "release": add("releases", "river"); break;
        case "grind": add("river", "grinds"); break;
        case "review": add("panels", "features"); break;
        case "blubird": add("blubird", "status"); break;
        case "coordinator": add("coordinators"); break;
        case "prd": add("river", "products", "features"); break;
        default: add("river", "releases", "ops", "products", "blubird");
      }
      break;
    }
    case "dispatch": add("dispatches", "features"); break;
    case "usage": {
      add("status");
      if (p?.kind === "settings") add("settings", "notify");
      break;
    }
    case "toast": break;
  }
  return [...out];
}

/** River, Me and the session list refetch debounced 1 s after a session event; everything else immediately. */
export const DEBOUNCED: ReadonlySet<LoadKey> = new Set<LoadKey>(["river", "me", "sessions", "features"]);
