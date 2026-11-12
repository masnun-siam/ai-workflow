import type { Action } from "../api/types";
import { ApiFailure } from "../api/client";

export type ActionDeps = {
  send: (method: Action["method"], path: string, body?: unknown) => Promise<unknown>;
  confirm: (text: string) => Promise<boolean>;
  navigate: (target: string) => void; // "#/..." or an https URL
  toast: (msg: string, level?: "info" | "warn" | "error") => void;
  onClears?: () => void;
  after?: () => void;
};

export function describeError(e: unknown): string {
  if (e instanceof ApiFailure) return e.body.error || `HTTP ${e.status}`;
  return e instanceof Error ? e.message : String(e);
}

/** Runs a server-built action exactly as given (API.md 4 `Action`). Returns true when it ran. */
export async function runAction(a: Action, d: ActionDeps): Promise<boolean> {
  if (a.confirm && !(await d.confirm(a.confirm))) return false;
  if (a.open) {
    d.navigate(a.open);
    return true;
  }
  try {
    await d.send(a.method, a.path, a.body);
  } catch (e) {
    d.toast(describeError(e), "error");
    return false;
  }
  d.toast(a.toast);
  if (a.clears) d.onClears?.();
  d.after?.();
  return true;
}

export const findAction = (actions: readonly Action[], key: string): Action | undefined =>
  actions.find((a) => a.key === key);
