import type { InboxItem, InboxType } from "../api/types";

/** What the drawer calls each raw inbox type. */
export const TYPE_LABEL: Record<InboxType, string> = {
  gh_auth: "GitHub sign-in", blubird_missing: "Plugin missing", question: "Question", prd_approval: "PRD approval", session_failed: "Session failed",
  limited: "Account limited", queued: "Queued", session_stalled: "Session stalled", review_cap: "Review round cap", review_approved: "Review approved",
  grind_paused: "Grind paused", needs_cleanup: "Needs cleanup", pr_conflict: "PR conflict", pr_ready: "PR ready to merge", release_note: "Release note",
  dispatch_needs: "Dispatch needs you", dispatch_stalled: "Dispatch stalled", dispatch_held: "Dispatch held", dispatch_merge: "Dispatch merge",
  dispatch_limited: "Dispatch limited", dispatch_done: "Dispatch done", away_summary: "While you were away", repo_unpublished: "Repo not on GitHub",
};
export const typeLabel = (t: string): string => TYPE_LABEL[t as InboxType] ?? t.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

const issueNo = (it: InboxItem): string => /\/(?:issues|pull)\/(\d+)/.exec(it.links.issue ?? it.links.pr ?? "")?.[1] ?? "";
const stepOf = (it: InboxItem): string => (it.detail ?? []).map((d) => /^step (.+)$/.exec(d)?.[1]).find(Boolean) ?? "";

/** The row title. A failed or stalled session's title is its raw prompt, so show the skill and issue instead. */
export function displayTitle(it: InboxItem): string {
  if (it.type !== "session_failed" && it.type !== "session_stalled") return it.title;
  const step = stepOf(it);
  const n = issueNo(it);
  if (!step && !n) return it.title.length > 80 ? `${it.title.slice(0, 77).trimEnd()}…` : it.title;
  return `${step || "session"}${n ? ` #${n}` : ""} ${it.type === "session_failed" ? "failed" : "stalled"}`;
}
