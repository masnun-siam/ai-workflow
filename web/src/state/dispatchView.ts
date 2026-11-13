/** Pure view logic for the Dispatches screens and the Start/Cleanup dialogs (kept out of the components so tests can reach it). */
import type { Dispatch, Lane } from "../api/types";

const DAY = 86400;
export const RECENT_DAYS = 14;

export const isLive = (d: Pick<Dispatch, "state">) => d.state === "running" || d.state === "paused";
export const isSettled = (l: Pick<Lane, "stage">) => l.stage === "closed" || l.stage === "skipped";
/** A lane that waits on the user: a question or failure (`needs_you`), or a session that stopped without finishing. */
export const wantsYou = (l: Pick<Lane, "needs_you" | "stalled">) => !!(l.needs_you || l.stalled);
/** Lanes that want the user. An ended dispatch asks for nothing: its open lanes are settled. */
export const needsLanes = (d: Dispatch): Lane[] => (isLive(d) ? d.lanes.filter((l) => wantsYou(l) && !isSettled(l)) : []);

/** "Epic: Payouts" and "Small changes: a, b" read as "Payouts" and "a, b". */
export const cleanTitle = (t: string): string => t.replace(/^(epic|small changes?)\s*:\s*/i, "");

/** "1 running · 3 paused", leaving out what is zero. */
export function runSummary(list: Pick<Dispatch, "state">[]): string {
  const running = list.filter((d) => d.state === "running").length;
  const paused = list.filter((d) => d.state === "paused").length;
  return [`${running} running`, paused ? `${paused} paused` : ""].filter(Boolean).join(" · ");
}

/** The last moment a dispatch did anything: when it ended, else its newest event, else when it began. Never the wall clock. */
export const frozenAt = (d: Dispatch): number =>
  d.ended_at ?? (d.events?.length ? Math.max(...d.events.map((e) => e.at)) : d.created_at);
export const dispatchSeconds = (d: Dispatch, now: number): number => (isLive(d) ? now : frozenAt(d)) - d.created_at;
/** A lane's running time; an open lane of an ended dispatch stops at the dispatch's last event. */
export function laneSeconds(d: Dispatch, l: Lane): number {
  if (!isLive(d) && !isSettled(l) && l.started_at != null) return Math.max(0, frozenAt(d) - l.started_at);
  return l.usage.seconds;
}

/** Live dispatches plus the last 14 days; a cancelled dispatch is hidden once a newer one runs the same epic. */
export function recentDispatches(list: Dispatch[], now: number): Dispatch[] {
  const newest = new Map<string, number>();
  for (const d of list) if (d.epic) newest.set(d.epic, Math.max(newest.get(d.epic) ?? 0, d.created_at));
  return list.filter((d) => {
    if (isLive(d)) return true;
    if (d.state === "cancelled" && d.epic && (newest.get(d.epic) ?? 0) > d.created_at) return false;
    return now - (d.ended_at ?? d.created_at) < RECENT_DAYS * DAY;
  });
}

export type Tab = "all" | "needs" | "live" | "done";
export const inTab = (d: Dispatch, t: Tab): boolean =>
  t === "all" || (t === "needs" ? needsLanes(d).length > 0 : t === "live" ? isLive(d) : !isLive(d));

// ---------- forms ----------
export type Num = { ok: true; value: number | null } | { ok: false; error: string };
/** "At most at once": empty means unset (never 0), otherwise a whole number 1–10. */
export function parseMax(text: string): Num {
  const t = text.trim();
  if (!t) return { ok: true, value: null };
  const n = Number(t);
  return Number.isInteger(n) && n >= 1 && n <= 10 ? { ok: true, value: n } : { ok: false, error: "Enter a whole number from 1 to 10" };
}
/** Cost cap in USD: empty means no cap, otherwise a number above 0. */
export function parseCost(text: string): Num {
  const t = text.trim();
  if (!t) return { ok: true, value: null };
  const n = Number(t);
  return Number.isFinite(n) && n > 0 ? { ok: true, value: n } : { ok: false, error: "Enter an amount above 0, or leave it empty" };
}

const KEY = /^[\w.-]+\/[\w.-]+#\d+$/;
/** "" when the target is fine (or empty), else what is wrong. An epic is `owner/repo#N` or `N`; small changes are a comma list. */
export function targetError(target: string, small: boolean): string {
  const t = target.trim();
  if (!t) return "";
  if (small) return t.split(/\s*,\s*/).every((k) => KEY.test(k)) ? "" : "Use owner/repo#N for each issue, separated by commas";
  return KEY.test(t) || /^#?\d+$/.test(t) || /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/issues\/\d+\/?$/.test(t) ? "" : "Use owner/repo#N or just the issue number";
}

/** A step argument is required unless its hint is empty or in [brackets]. */
export const argRequired = (hint: string | undefined): boolean => !!hint?.trim() && !hint.trim().startsWith("[");

// ---------- Activity ----------
/** The last folder of a path ("/Users/x/app" → "app"), or the repo name of owner/name. */
export const baseName = (p: string | null | undefined): string => {
  const parts = (p ?? "").split("/").filter(Boolean);
  return parts[parts.length - 1] ?? "";
};

/** `https://github.com/o/r/issues/12` → `o/r#12`; `…/orgs/o/projects/3/…` → `o · project 3`; anything else unchanged. */
export function friendlyRef(s: string): string {
  const issue = /github\.com\/([\w.-]+\/[\w.-]+)\/(?:issues|pull)\/(\d+)/.exec(s);
  if (issue) return `${issue[1]}#${issue[2]}`;
  const proj = /github\.com\/(?:orgs|users)\/([\w.-]+)\/projects\/(\d+)/.exec(s);
  if (proj) return `${proj[1]} · project ${proj[2]}`;
  return s;
}
