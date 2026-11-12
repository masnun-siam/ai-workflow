import { signal } from "@preact/signals";

export type Look = "classic" | "console" | "river";
export type Mode = "system" | "dark" | "light";
export type Layout = "drawer" | "split";
export type Prefs = { look: Look; mode: Mode; layout: Layout };

export const DEFAULT_PREFS: Prefs = { look: "classic", mode: "system", layout: "drawer" };
export const LOOKS: Look[] = ["classic", "console", "river"];
export const MODES: Mode[] = ["system", "dark", "light"];
export const LAYOUTS: Layout[] = ["drawer", "split"];
const KEY = "setu.prefs.v1";

type StorageLike = Pick<Storage, "getItem" | "setItem">;
function store(): StorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null; // blocked storage
  }
}

export function sanitize(raw: unknown): Prefs {
  const o = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const pick = <T extends string>(v: unknown, list: T[], d: T): T => (list.includes(v as T) ? (v as T) : d);
  return {
    look: pick(o.look, LOOKS, DEFAULT_PREFS.look),
    mode: pick(o.mode, MODES, DEFAULT_PREFS.mode),
    layout: pick(o.layout, LAYOUTS, DEFAULT_PREFS.layout),
  };
}
export function loadPrefs(s: StorageLike | null = store()): Prefs {
  try {
    return sanitize(JSON.parse(s?.getItem(KEY) ?? "{}"));
  } catch {
    return { ...DEFAULT_PREFS };
  }
}
export function savePrefs(p: Prefs, s: StorageLike | null = store()): void {
  try {
    s?.setItem(KEY, JSON.stringify(p));
  } catch {
    /* ignore: the page renders without storage */
  }
}
export function next<T>(list: T[], cur: T): T {
  return list[(list.indexOf(cur) + 1) % list.length] as T;
}
/** Per-viewer string conveniences (selected product etc.). Never throws. */
export function lsGet(key: string): string | null {
  try {
    return store()?.getItem(key) ?? null;
  } catch {
    return null;
  }
}
export function lsSet(key: string, v: string): void {
  try {
    store()?.setItem(key, v);
  } catch {
    /* ignore */
  }
}

export const prefs = signal<Prefs>(loadPrefs());

export function setPref<K extends keyof Prefs>(k: K, v: Prefs[K]): void {
  prefs.value = { ...prefs.value, [k]: v };
  savePrefs(prefs.value);
  applyPrefs(prefs.value);
}
export function applyPrefs(p: Prefs, doc: Document | undefined = globalThis.document): void {
  if (!doc) return;
  doc.body.className = `skin-${p.look}`;
  if (p.mode === "system") doc.documentElement.removeAttribute("data-theme");
  else doc.documentElement.setAttribute("data-theme", p.mode);
}
