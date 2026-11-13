import { signal } from "@preact/signals";
import type { RegistryStep } from "../api/extra";

export type ToastMsg = { msg: string; level: "info" | "warn" | "error"; path?: string };
export const toastMsg = signal<ToastMsg | null>(null);
let toastTimer: ReturnType<typeof setTimeout> | undefined;
export function toast(msg: string, level: ToastMsg["level"] = "info", path?: string): void {
  toastMsg.value = { msg, level, path };
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toastMsg.value = null), level === "error" ? 6000 : 2600);
}

export const paletteOpen = signal(false);
/** The top-bar repo switcher popover (g r). */
export const repoOpen = signal(false);
export const helpOpen = signal(false);
export const connected = signal(false);
export const detailOpen = signal(false);

export type ConfirmReq = { text: string; resolve: (yes: boolean) => void };
export const confirmReq = signal<ConfirmReq | null>(null);
export function askConfirm(text: string): Promise<boolean> {
  return new Promise((resolve) => {
    confirmReq.value = { text, resolve: (y) => { confirmReq.value = null; resolve(y); } };
  });
}

/** The "start a run" dialog: a registry step (or free text when step is null) with optional presets. */
export type StartReq = { step: RegistryStep | null; repo?: string; args?: string };
export const startReq = signal<StartReq | null>(null);

/** The Create box (n, New): "What should change?" -> a feature (create-prd), a small change or a bug (report-bug).
 *  The draft and the route survive Cancel; opening with an empty draft starts on Feature. */
export type CreateRoute = "feature" | "small" | "bug";
export const createOpen = signal(false);
export const createDraft = signal("");
export const createRoute = signal<CreateRoute>("feature");
export function openCreate(text?: string): void {
  // only reopening a kept draft keeps its route; new text (from the palette) starts on Feature too
  if (text || !createDraft.value.trim()) createRoute.value = "feature";
  if (text) createDraft.value = text;
  createOpen.value = true;
}

/** Selection in the list screens: river (stage, card), others index. */
export const sel = signal({ stage: 3, card: 0, inbox: 0, runs: 0, ops: 0 });
export function setSel(patch: Partial<ReturnType<typeof sel.peek>>): void {
  sel.value = { ...sel.peek(), ...patch };
}
export const clamp = (v: number, a: number, b: number): number => Math.max(a, Math.min(b, v));
