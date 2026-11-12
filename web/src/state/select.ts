import { computed, signal } from "@preact/signals";
import type { Action, InboxGroup, InboxItem, Session } from "../api/types";
import { activityTab, dispatches, dropped, inbox, inScope, only, ops, river, sessionList, status } from "./data";
import { clamp, sel } from "./ui";
import { route } from "./route";
import type { Target } from "../components/Detail";
import { targetActions, targetRound } from "../components/Detail";
import { quickOptions } from "./answer";

export const GROUPS: [InboxGroup, string][] = [
  ["block", "Blocking"], ["answer", "Questions"], ["decide", "Decide"], ["fix", "Fix"], ["setup", "Setup"], ["wait", "Waiting"],
];

export const stages = computed(() =>
  (river.value?.stages ?? []).map((s) => ({ ...s, cards: s.cards.filter((c) => !dropped.value.has(c.id) && cardInScope(c.repo)) })));
/** River cards carry the repo name only (last slug segment). */
const cardInScope = (name: string) => !only.value || !name || only.value.split("/").pop()!.toLowerCase() === name.toLowerCase();

export const inboxItems = computed<InboxItem[]>(() => {
  const order = GROUPS.map((g) => g[0]);
  const summaryShown = !!status.value?.away.summary; // the Inbox shows it as "While you were away"
  return (inbox.value?.items ?? []).filter((i) => !dropped.value.has(i.key) && inScope(i.repo) && !(summaryShown && i.type === "away_summary"))
    .map((it, n) => ({ it, n })).sort((a, b) => order.indexOf(a.it.group) - order.indexOf(b.it.group) || a.n - b.n).map((x) => x.it);
});

export const RUNNING: ReadonlySet<string> = new Set(["starting", "running", "waiting"]);
/** Activity history filters (old aiw Activity): text search and result. The repo comes from `?only=`. */
export const activityQuery = signal("");
export const activityResult = signal<"all" | "done" | "failed" | "stopped">("all");
export const runList = computed<Session[]>(() => {
  const q = activityQuery.value.trim().toLowerCase();
  const res = activityResult.value;
  return (sessionList.value?.sessions ?? []).filter((s) => !s.dismissed && inScope(s.repo)
    && (res === "all" || s.status === res)
    && (!q || `${s.title} ${s.skill ?? ""} ${s.command} ${s.repo ?? ""}`.toLowerCase().includes(q)));
});
export const runningCount = computed(() => (sessionList.value?.sessions ?? []).filter((s) => RUNNING.has(s.status)).length);
export const dispatchList = computed(() => (dispatches.value ?? []).filter((d) =>
  !only.value || d.lanes.some((l) => inScope(l.repo)) || (!!d.epic && inScope(d.epic.split("#")[0]))));
export const dispatchingCount = computed(() => (dispatches.value ?? []).filter((d) => d.state === "running").length);
export const opsRows = computed(() => ops.value?.rows ?? []);

export const needCount = computed(() => inbox.value?.count ?? 0);

/** What the selection points at on the current screen. */
export const currentTarget = computed<Target>(() => {
  const r = route.value;
  const s = sel.value;
  if (r.screen === "river") {
    const st = stages.value[clamp(s.stage, 0, Math.max(0, stages.value.length - 1))];
    const card = st?.cards[clamp(s.card, 0, Math.max(0, st.cards.length - 1))];
    return card ? { kind: "card", card } : null;
  }
  if (r.screen === "inbox") { const item = inboxItems.value[clamp(s.inbox, 0, Math.max(0, inboxItems.value.length - 1))]; return item ? { kind: "inbox", item } : null; }
  if (r.screen === "activity" && !r.id && activityTab.value === "sessions") { const session = runList.value[clamp(s.runs, 0, Math.max(0, runList.value.length - 1))]; return session ? { kind: "session", session } : null; }
  if (r.screen === "ops") { const row = opsRows.value[clamp(s.ops, 0, Math.max(0, opsRows.value.length - 1))]; return row ? { kind: "ops", row } : null; }
  return null;
});

export const quickCount = computed(() => quickOptions(targetRound(currentTarget.value)?.round).length);
export const keyActions = (extra: readonly Action[]) => [...targetActions(currentTarget.value), ...extra];
export const hasList = (screen: string): "river" | "list" | null =>
  screen === "river" ? "river" : screen === "inbox" || screen === "ops" || (screen === "activity" && activityTab.value === "sessions" && !route.value.id) ? "list" : null;

export function listLength(screen: string): number {
  if (screen === "inbox") return inboxItems.value.length;
  if (screen === "ops") return opsRows.value.length;
  return runList.value.length;
}
