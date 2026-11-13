import { signal } from "@preact/signals";
import type { RegistryStep } from "../api/extra";

export type ToastMsg = { msg: string; level: "info" | "warn" | "error"; path?: string };
export const toastMsg = signal<ToastMsg | null>(null);
let toastTimer: ReturnType<typeof setTimeout> | undefined;
let toastEnds = 0;
let toastLeft = 0;
/** Errors and toasts with an action (a path to open) stay at least 6 s; the rest 2.6 s. */
export const toastMs = (level: ToastMsg["level"], path?: string): number => (level === "error" || path ? 6000 : 2600);
function arm(ms: number): void {
  clearTimeout(toastTimer);
  toastEnds = Date.now() + ms;
  toastTimer = setTimeout(() => (toastMsg.value = null), ms);
}
export function toast(msg: string, level: ToastMsg["level"] = "info", path?: string): void {
  toastMsg.value = { msg, level, path };
  arm(toastMs(level, path));
}
/** Hover or focus on the toast: stop the clock. */
export function holdToast(): void {
  if (!toastMsg.peek() || !toastEnds) return;
  clearTimeout(toastTimer);
  toastLeft = Math.max(1500, toastEnds - Date.now());
  toastEnds = 0;
}
/** Pointer or focus leaves: run out what was left. */
export function releaseToast(): void {
  if (toastMsg.peek() && !toastEnds) arm(toastLeft);
}

export const paletteOpen = signal(false);
/** The top-bar repo switcher popover (g r). */
export const repoOpen = signal(false);
export const helpOpen = signal(false);
export const connected = signal(false);
export const detailOpen = signal(false);

export type ConfirmReq = { text: string; danger: boolean; resolve: (yes: boolean) => void };
export const confirmReq = signal<ConfirmReq | null>(null);
/** `danger`: the confirm destroys or stops something, so focus starts on "No". */
export function askConfirm(text: string, danger = false): Promise<boolean> {
  return new Promise((resolve) => {
    confirmReq.value = { text, danger, resolve: (y) => { confirmReq.value = null; resolve(y); } };
  });
}

/** The "start a run" dialog: a registry step (or free text when step is null) with optional presets. */
export type StartReq = { step: RegistryStep | null; repo?: string; args?: string };
export const startReq = signal<StartReq | null>(null);

/** The Create box (n, New): "What should change?" -> a feature (create-prd), a small change or a bug (report-bug).
 *  The draft and the route survive Cancel; opening with an empty draft starts on Feature.
 *  jev may preselect the route while typing (createJevPick) until the user clicks one (createRouteTouched). */
export type CreateRoute = "feature" | "small" | "bug";
export const createOpen = signal(false);
export const createDraft = signal("");
export const createRoute = signal<CreateRoute>("feature");
export const createRouteTouched = signal(false);
export const createJevPick = signal<{ route: CreateRoute; p: number } | null>(null);
export function openCreate(text?: string): void {
  // only reopening a kept draft keeps its route; new text (from the palette) starts on Feature too
  if (text || !createDraft.value.trim()) {
    createRoute.value = "feature";
    createRouteTouched.value = false;
    createJevPick.value = null;
  }
  if (text) createDraft.value = text;
  createOpen.value = true;
}

/** Selection in the list screens: river (stage, card), others index. */
export const sel = signal({ stage: 3, card: 0, inbox: 0, runs: 0, ops: 0 });
export function setSel(patch: Partial<ReturnType<typeof sel.peek>>): void {
  sel.value = { ...sel.peek(), ...patch };
}
export const clamp = (v: number, a: number, b: number): number => Math.max(a, Math.min(b, v));
