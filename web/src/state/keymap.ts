import type { Action } from "../api/types";
import { answerKeyIndex } from "./answer";
import type { ScreenId } from "./route";
import { SCREENS } from "./route";

export type KeyEvt = { key: string; meta?: boolean; ctrl?: boolean; alt?: boolean; typing?: boolean };
export type KeyCtx = {
  screen: ScreenId | "prd";
  overlay: boolean;                 // palette, help, confirm or start dialog is open (they own their keys)
  actions: readonly Action[];       // current item's actions + the screen's actions
  quickOptions: number;             // options answerable with a/b/c (0 = none)
  nav: "river" | "list" | null;     // does the screen have a selectable list
};
export type Cmd =
  | { t: "go"; screen: ScreenId } | { t: "palette" } | { t: "help" } | { t: "escape" }
  | { t: "mode" } | { t: "look" } | { t: "layout" }
  | { t: "answer"; index: number } | { t: "action"; key: string }
  | { t: "move"; dx: number; dy: number } | { t: "enter" } | { t: "screen"; key: string };

/** The whole keyboard map (prototype HINTS + 1-7, `:`/Cmd-K, `.`, `s`, `L`, `?`). Returns null for keys we ignore. */
export function resolveKey(e: KeyEvt, c: KeyCtx): Cmd | null {
  const k = e.key;
  if ((e.meta || e.ctrl) && k.toLowerCase() === "k") return { t: "palette" };
  if (k === "Escape") return { t: "escape" };
  if (e.typing || c.overlay) return null;
  if (e.meta || e.ctrl || e.alt) return null;
  if (k === ":") return { t: "palette" };
  if (k === "?") return { t: "help" };
  if (k === ".") return { t: "mode" };
  if (k === "s") return { t: "look" };
  if (k === "L") return { t: "layout" };
  if (/^[1-7]$/.test(k)) return { t: "go", screen: SCREENS[Number(k) - 1]![0] };
  if (c.nav) {
    if (k === "j" || k === "ArrowDown") return { t: "move", dx: 0, dy: 1 };
    if (k === "k" || k === "ArrowUp") return { t: "move", dx: 0, dy: -1 };
    if (c.nav === "river" && (k === "h" || k === "ArrowLeft")) return { t: "move", dx: -1, dy: 0 };
    if (c.nav === "river" && (k === "l" || k === "ArrowRight")) return { t: "move", dx: 1, dy: 0 };
  }
  const ai = answerKeyIndex(k);
  if (ai >= 0 && ai < c.quickOptions) return { t: "answer", index: ai };
  if (k.length === 1 && c.actions.some((a) => a.key === k)) return { t: "action", key: k };
  if (k === "Enter" && c.nav) return { t: "enter" };
  if (k.length === 1) return { t: "screen", key: k };
  return null;
}

export const HINTS: Record<string, [string, string][]> = {
  river: [["h/l", "stage"], ["j/k", "card"], ["⏎", "open"], ["a/b/c", "answer"]],
  inbox: [["j/k", "move"], ["⏎", "open"], ["a/b/c", "answer"]],
  runs: [["j/k", "move"], ["⏎", "open"]],
  releases: [["c", "cut"], ["y", "dry run"], ["g", "grind"], ["n", "note"], ["p", "post"], ["e", "edit"]],
  ops: [["j/k", "move"], ["⏎", "run"]],
  me: [["r", "reconcile"], ["w", "weekly"]],
  settings: [["u", "update"], ["i", "reinstall"]],
  prd: [["esc", "back"]],
};
