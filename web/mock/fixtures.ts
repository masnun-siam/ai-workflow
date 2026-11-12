// Mock data for `npm run dev:mock` and the smoke tests. Typed by src/api/types.ts.
import type {
  Action, Card, Coordinator, Dispatch, InboxItem, Me, NotifySettings, Ops, Panel, Product, Release, ReleaseRepo,
  Repo, ReviewConfig, River, Round, Session, Settings, Status, TranscriptEvent, GrindStatus, AccountUsage, Away, PRD, FeatureIssue, FeatureList, ChangesList, IssueView, PRView,
} from "../src/api/types";
import type { RegistryStep } from "../src/api/extra";

const now = Date.now();
const iso = (minAgo: number) => new Date(now - minAgo * 60000).toISOString();
const SID = (n: number) => `20261112T0${n}0000000000Z-0000000${n}`;

export const PRODUCT = "acme/wasensi-docs";
const open = (id: string): Action => ({ key: "o", label: "Open session", method: "POST", path: "/api/noop", toast: "", open: `#/sessions/${id}` });
const stop = (id: string): Action => ({ key: "x", label: "Stop", method: "POST", path: `/api/sessions/${id}/stop`, toast: "Stopped", clears: true, confirm: "Stop this run?" });
const start = (key: string, label: string, step: string, args: string, repo: string, extra: Partial<Action> = {}): Action => ({
  key, label, method: "POST", path: "/api/sessions", body: { step, args, repo, guard: true }, toast: `Started ${step} ${args}`.trim(), ...extra,
});

const q1: Round = { id: "round-1", status: "pending", allowFreeText: true, risk: { p: 0.31 }, questions: [{
  header: "Migration", question: "Migration adds NOT NULL payout_batch_id to orders (2.1M rows). How do existing rows get a value?",
  multiSelect: false, allowFreeText: true, recommended: "Nullable + backfill job",
  options: [{ label: "Nullable + backfill job", description: "Add the column nullable, backfill in a job, then tighten", preview: "ALTER TABLE orders ADD payout_batch_id NULL;" },
    { label: "Backfill in migration", description: "One long migration" }, { label: "Legacy batch default", description: "Default row per merchant" }] }] };
const q2: Round = { id: "round-2", status: "pending", allowFreeText: false, questions: [
  { header: "Scope", question: "Which exports need the VAT column?", multiSelect: true, allowFreeText: true, recommended: null,
    options: [{ label: "CSV", description: "orders.csv" }, { label: "XLSX", description: "orders.xlsx" }, { label: "PDF statement", description: "" }] },
  { header: "Rollout", question: "Ship behind a flag?", multiSelect: false, allowFreeText: false, recommended: "Yes",
    options: [{ label: "Yes", description: "" }, { label: "No", description: "" }] }] };

const tok = { input: 12000, cached: 80000, output: 4300 };
const base: Session = {
  id: "", step: null, skill: null, kind: null, title: "", command: "", repo: null, repo_path: null, link: null, session_id: null,
  status: "running", model: "opus", effort: "high", cost: 1.2, tokens: tok, started_at: iso(30), ended_at: null, duration_s: 1800,
  waiting: false, pending_question: null, error: null, note: null, pending_answer: null, queued_prompt: null, account: "work",
  limit_resets_at: null, limit_type: null, auto_resume: null, hold: false, no_repo: false, vault_folder: null, dismissed: false,
  panel: null, dispatch: null, hooks: 0, resume_command: null,
};
const S = (p: Partial<Session>): Session => ({ ...base, ...p });
export const sessions: Session[] = [
  S({ id: SID(1), step: "implement-issue", skill: "blubird:implement-issue", title: "#1012 Payout batch model", command: "/blubird:implement-issue 1012",
    repo: "acme/wasensi-backend", link: { owner: "acme", repo: "wasensi-backend", issue: 1012 }, status: "waiting", waiting: true, pending_question: q1, cost: 4.12, hooks: 2, duration_s: 2280, resume_command: "claude --resume abc" }),
  S({ id: SID(2), step: "implement-issue", skill: "blubird:implement-issue", title: "#1013 Batch scheduler", command: "/blubird:implement-issue 1013",
    repo: "acme/wasensi-backend", link: { owner: "acme", repo: "wasensi-backend", issue: 1013 }, cost: 2.3, duration_s: 1320 }),
  S({ id: SID(3), step: "pr-grind", skill: "pr-grind", kind: "grind", title: "Release PR #1040", command: "/pr-grind 1040", repo: "acme/wasensi-backend", cost: 3.88, duration_s: 3840 }),
  S({ id: SID(4), step: "project-coordinator", skill: "blubird:project-coordinator", kind: "coordinator", title: "Coordinator label:payments", command: "/blubird:project-coordinator label:payments", repo: "acme/bop-bd", cost: 6.8, duration_s: 7800 }),
  S({ id: SID(5), step: "verifier-locally", skill: "blubird:verifier-locally", title: "#455 phpstan failed", command: "/blubird:verifier-locally", repo: "acme/bop-bd", status: "failed", error: "phpstan exited 1", ended_at: iso(12), cost: 0.41, duration_s: 360 }),
  S({ id: SID(6), step: "reproduce-bug", skill: "blubird:reproduce-bug", title: "#1044 CSV drops VAT", command: "/blubird:reproduce-bug 1044", repo: "acme/wasensi-backend", status: "limited", limit_resets_at: Math.floor(now / 1000) + 3600, limit_type: "five_hour", auto_resume: true, cost: 0.77, duration_s: 540 }),
  S({ id: SID(7), step: "security-sweep", skill: "blubird:security-sweep", title: "Security sweep weekly", command: "/blubird:security-sweep", repo: "acme/wasensi-docs", status: "done", ended_at: iso(300), cost: 1.2, duration_s: 840 }),
  S({ id: SID(8), step: "refine-issues", skill: "blubird:refine-issues", title: "Refine epic 941", command: "/blubird:refine-issues 941", repo: "acme/wasensi-docs", status: "queued", queued_prompt: "also check #942" }),
  S({ id: SID(9), step: null, skill: null, title: "Why is the build slow?", command: "Why is the build slow?", status: "waiting", waiting: true, pending_question: q2, no_repo: true }),
];

export const transcripts: Record<string, TranscriptEvent[]> = {
  [SID(1)]: [
    { kind: "text", text: "Creating the worktree issue-1012-payout-batch from staging." },
    { kind: "tool", name: "Bash", input: { command: "git worktree add .worktrees/issue-1012 -b issue-1012-payout-batch origin/staging" } },
    { kind: "hook", name: "mask-secrets", event: "UserPromptSubmit", text: "2 secrets masked", blocked: false },
    { kind: "text", text: "Writing the failing test PayoutBatchTest first." },
    { kind: "tool", name: "Edit", input: { file_path: "tests/PayoutBatchTest.php" } },
    { kind: "hook", name: "claude-md-guard", event: "PreToolUse", text: "Edit CLAUDE.md denied", blocked: true },
    { kind: "result", cost: 4.12, is_error: false, text: "Waiting for your answer on the migration.", tokens: tok },
  ],
};

const C = (p: Partial<Card> & Pick<Card, "id" | "stage" | "title">): Card => ({
  meta: "", tag: "", tone: "", need: false, need_kind: null, live: false, skill: "", repo: "", log: [], ask: null, note: null, links: {}, actions: [], ...p,
});
export const note = "@here\nRelease Note - 12 November 2026\nMerchants can now see payouts grouped into weekly batches.\n\nPayouts\n- Weekly batches with one statement each\n\nCC: @Ashique vai, @Najmul vai, @Abir vai";
export const river: River = {
  product: PRODUCT, stale: [], fetched_at: iso(1),
  stages: [
    { id: "prd", name: "PRD", skills: "create-prd · map-prds", hot: true, cards: [
      C({ id: "prd:kyc", stage: "prd", title: "Merchant KYC re-check", meta: "draft · wasensi-docs", tag: "draft", tone: "c-w", skill: "blubird:create-prd", repo: "wasensi-docs", log: ["Interview 6 of 11 questions answered", "Paused 2 days ago"],
        actions: [start("o", "Continue interview", "create-prd", "docs/prds/kyc/recheck.md", "acme/wasensi-docs")] }),
      C({ id: "prd:pay", stage: "prd", title: "Merchant payouts v2", meta: "9 tasks planned", tag: "approve", tone: "c-w", need: true, need_kind: "Approval", skill: "blubird:create-prd", repo: "wasensi-docs",
        log: ["PRD written: docs/prds/payouts/batches.md", "Waiting for approval"], links: { prd: "#/prd?repo=acme/wasensi-docs&path=docs/prds/payouts/batches.md" },
        actions: [start("e", "Approve + create epic", "create-prd", "docs/prds/payouts/batches.md — the team has reviewed it; approve it", "acme/wasensi-docs", { primary: true, clears: true }),
          { key: "r", label: "Read PRD", method: "POST", path: "/api/noop", toast: "", open: "#/prd?repo=acme/wasensi-docs&path=docs/prds/payouts/batches.md" }] })] },
    { id: "tasks", name: "Tasks", skills: "create-tasks", hot: false, cards: [
      C({ id: "epic:acme/wasensi-docs#941", stage: "tasks", title: "Courier rate cache", meta: "epic #941 · 5 issues", tag: "epic", tone: "c-q", skill: "blubird:create-tasks", repo: "wasensi-docs", log: ["5 child issues with blocked-by links"],
        actions: [start("f", "Refine all 5", "refine-issues", "941", "acme/wasensi-docs")] })] },
    { id: "refine", name: "Refine", skills: "refine-issues · reproduce-bug", hot: false, cards: [
      C({ id: "issue:acme/wasensi-backend#1044", stage: "refine", title: "#1044 CSV drops VAT", meta: "bug · reproducing", tag: "bug", tone: "c-b", live: true, skill: "blubird:reproduce-bug", repo: "wasensi-backend",
        log: ["Timeline built from the issue + 2 Slack threads", "Reproducing locally"], actions: [open(SID(6))] }),
      C({ id: "issue:acme/wasensi-web#1015", stage: "refine", title: "#1015 Statement PDF", meta: "Backlog", tag: "backlog", repo: "wasensi-web", actions: [start("f", "Refine", "refine-issues", "1015", "acme/wasensi-web")] })] },
    { id: "implement", name: "Implement", skills: "implement-issue · coordinator", hot: true, cards: [
      C({ id: "session:" + SID(1), stage: "implement", title: "#1012 Payout batch model", meta: "38m · $4.12", tag: "question", tone: "c-q", need: true, need_kind: "Question", skill: "blubird:implement-issue", repo: "wasensi-backend",
        log: ["Worktree issue-1012-payout-batch from staging", "Failing test PayoutBatchTest written", "Asked you 4m ago"], ask: { session_id: SID(1), round: q1 }, actions: [open(SID(1)), stop(SID(1))] }),
      C({ id: "session:" + SID(2), stage: "implement", title: "#1013 Batch scheduler", meta: "CI running · 22m", tag: "ci", tone: "c-q", live: true, skill: "blubird:implement-issue", repo: "wasensi-backend", log: ["Draft PR #1041 opened", "CI running (3/5 jobs)"], actions: [open(SID(2))] }),
      C({ id: "issue:acme/wasensi-backend#1031", stage: "implement", title: "#1031 Retry on 429", meta: "Ready", tag: "ready", tone: "c-o", repo: "wasensi-backend",
        actions: [start("i", "Implement", "implement-issue", "1031", "acme/wasensi-backend", { primary: true }), { key: "d", label: "Add to dispatch", method: "POST", path: "/api/dispatches/d1a2b3c4d5e6/lanes", body: { issues: ["acme/wasensi-backend#1031"] }, toast: "Added to dispatch" }] })] },
    { id: "review", name: "Review", skills: "pr-review · peer · grind", hot: false, cards: [
      C({ id: "pr:acme/wasensi-backend#1029", stage: "review", title: "#1019 Slow search", meta: "PR #1029 · 3 comments", tag: "review", tone: "c-w", skill: "blubird:pr-review", repo: "wasensi-backend", log: ["2 human comments, 1 bot comment"],
        actions: [start("x", "Fix comments", "pr-review", "1029 --fix", "acme/wasensi-backend"), start("g", "Grind", "pr-grind", "1029", "acme/wasensi-backend")] }),
      C({ id: "pr:acme/wasensi-web#1035", stage: "review", title: "#1033 Dashboard status", meta: "grind round 2 · CI ok", tag: "grind", tone: "c-o", live: true, skill: "pr-grind", repo: "wasensi-web", log: ["Round 1: 3 findings, 2 fixed, 1 rebutted"],
        links: { pr: "https://github.com/acme/wasensi-web/pull/1035" }, actions: [{ key: "o", label: "Open PR", method: "POST", path: "/api/noop", toast: "", open: "https://github.com/acme/wasensi-web/pull/1035" }] })] },
    { id: "release", name: "Release", skills: "release-pr · pr-grind", hot: false, cards: [
      C({ id: "repo:acme/wasensi-web", stage: "release", title: "wasensi-web", meta: "6 PRs on staging", tag: "release", skill: "release-pr", repo: "wasensi-web",
        actions: [{ key: "r", label: "Cut release", method: "POST", path: "/api/releases", body: { repo: "acme/wasensi-web" }, toast: "Started release-pr" }, { key: "y", label: "Dry run", method: "POST", path: "/api/releases", body: { repo: "acme/wasensi-web", dry_run: true }, toast: "Dry run started" }] }),
      C({ id: "release:r-20261112T090000Z-aaaaaa", stage: "release", title: "Release PR #1040", meta: "grind round 3", tag: "grind", tone: "c-q", live: true, skill: "pr-grind", repo: "wasensi-backend", log: ["release-pr: 14 PRs, 1 migration", "Round 3 waiting on the bot"], actions: [open(SID(3))] })] },
    { id: "notify", name: "Notify", skills: "release-note", hot: true, cards: [
      C({ id: "release:r-20261112T080000Z-bbbbbb", stage: "notify", title: "Release #1036", meta: "merged 20m ago", tag: "notify", tone: "c-w", need: true, need_kind: "Release", skill: "release-note", repo: "wasensi-backend", note,
        actions: [{ key: "p", label: "Post to #dc-supports", method: "POST", path: "/api/releases/r-20261112T080000Z-bbbbbb/post", toast: "Posted once to #dc-supports", primary: true, clears: true, confirm: "Post the note to #dc-supports? It is never retried." },
          { key: "e", label: "Edit note", method: "POST", path: "/api/noop", toast: "", open: "#/releases" }] })] },
  ],
};

const I = (p: Partial<InboxItem> & Pick<InboxItem, "key" | "group" | "type" | "kind" | "title">): InboxItem => ({ repo: null, at: iso(10), urgency: 1, links: {}, actions: [], ...p });
export const inboxItems: InboxItem[] = [
  I({ key: "question:" + SID(1), group: "answer", type: "question", kind: "Question", title: "#1012 Payout batch model", repo: "acme/wasensi-backend", session_id: SID(1), round: q1, actions: [open(SID(1)), stop(SID(1))] }),
  I({ key: "question:" + SID(9), group: "answer", type: "question", kind: "Question", title: "Why is the build slow?", session_id: SID(9), round: q2, actions: [open(SID(9))] }),
  I({ key: "prd:pay", group: "decide", type: "prd_approval", kind: "Approval", title: "Merchant payouts v2", repo: "acme/wasensi-docs", actions: river.stages[0]!.cards[1]!.actions }),
  I({ key: "failed:" + SID(5), group: "fix", type: "session_failed", kind: "Failed", title: "#455 phpstan failed", repo: "acme/bop-bd", session_id: SID(5),
    detail: ["RateCache.php:41 missing return type", "RateCache.php:77 undefined method get()"], actions: [{ key: "f", label: "Resume with fix", method: "POST", path: `/api/sessions/${SID(5)}/resume`, toast: "Resumed", clears: true, primary: true }, open(SID(5))] }),
  I({ key: "release:b", group: "decide", type: "release_note", kind: "Release", title: "Release #1036 note", repo: "acme/wasensi-backend", note, actions: river.stages[6]!.cards[0]!.actions }),
  I({ key: "limited:" + SID(6), group: "wait", type: "limited", kind: "Limited", title: "#1044 waits for the limit reset", repo: "acme/wasensi-backend", actions: [open(SID(6))] }),
];

const usage = (label: string, p5: number, p7: number): AccountUsage => ({ label, cmd: "claude", five_hour: { pct: p5, resets_at: iso(-120) }, seven_day: { pct: p7, resets_at: iso(-3000) }, at: Math.floor(now / 1000), error: null, limit: {} });
export const away: Away = { active: false, until: null, started: null, decisions: 0, held: 0, summary: null };
export const status: Status = {
  version: "0.1.0", boot_id: "boot1", gh: { ok: true, login: "siam", error: "" }, usage: [usage("work", 62, 41), usage("personal", 8, 3)], away, migrated: true,
  poller: { remaining: 4800, reset_at: null },
  blubird: { installed: true, version: "0.26.3", latest: "0.26.3", update_available: false, install_path: "~/.claude/plugins/blubird", marketplace: "agentic-workflow", skills: ["create-prd", "implement-issue"], hooks: ["claude-md-guard", "mask-secrets", "idle-guard"], busy: "", error: "" },
};

export const products: Product[] = [
  { docs_repo: PRODUCT, name: "Wasensi", path: "/code/wasensi-docs", repos: [
    { name: "backend", role: "api", repo: "acme/wasensi-backend", path: "/code/wasensi-backend", cloned: true }, { name: "web", role: "ui", repo: "acme/wasensi-web", path: "/code/wasensi-web", cloned: true }] },
  { docs_repo: "acme/bop-bd-docs", name: "BOP BD", path: "/code/bop-docs", repos: [{ name: "bop-bd", role: "app", repo: "acme/bop-bd", path: "/code/bop-bd", cloned: true }, { name: "bop-bd-ui", role: "ui", repo: "acme/bop-bd-ui", path: "", cloned: false }] },
];
export const repos: Repo[] = [
  { slug: "acme/wasensi-docs", path: "/code/wasensi-docs", product: PRODUCT }, { slug: "acme/wasensi-backend", path: "/code/wasensi-backend", product: PRODUCT },
  { slug: "acme/wasensi-web", path: "/code/wasensi-web", product: PRODUCT }, { slug: "acme/bop-bd", path: "/code/bop-bd", product: "acme/bop-bd-docs" },
];

const so = (id: string, kind: string): Action => ({ key: "r", label: "Run", method: "POST", path: "/api/sessions", body: { step: id, repo: "acme/wasensi-backend" }, toast: `Started ${id}` });
export const ops: Ops = { product: PRODUCT, rows: [
  { step: "agentic-onboard", label: "blubird:agentic-onboard", scope: "each repo", summary: "2/3 repos ready", targets: [{ repo: "acme/wasensi-web", last: null, note: "missing" }], actions: [so("agentic-onboard", "")] },
  { step: "security-sweep", label: "blubird:security-sweep", scope: "docs repo", summary: "last 10 Nov · 3 fix actions", targets: [{ repo: PRODUCT, last: { id: SID(7), status: "done", started_at: iso(300), ended_at: iso(290), cost: 1.2 }, note: "" }], actions: [so("security-sweep", "")] },
  { step: "docs-updater", label: "blubird:docs-updater", scope: "each repo", summary: "41 commits since last run", targets: [], actions: [so("docs-updater", ""), { ...so("docs-updater", ""), key: "f", label: "Full" }] },
  { step: "skill-feedback", label: "blubird:skill-feedback", scope: "any repo", summary: "12 PRs since last reconcile", targets: [], actions: [so("skill-feedback", "")] },
] };
export const me: Me = {
  day_end: { date: "2026-11-12", reconciled: false, missing_days: 2, last: null }, weekly: { week: 46, drafted: false, last: null }, usage: status.usage,
  cost: { today_count: 7, today_cost: 17.11, month_count: 148, month_cost: 212 },
  actions: [{ key: "r", label: "Reconcile today", method: "POST", path: "/api/sessions", body: { step: "day-end-reconcile" }, toast: "Started day-end-reconcile", primary: true },
    { key: "w", label: "Draft week 46", method: "POST", path: "/api/sessions", body: { step: "weekly-review" }, toast: "Started weekly-review" }],
};

const grind: GrindStatus = { repo: "acme/wasensi-backend", pr: 1040, state: "running", mode: "deep", rounds: 3, reason: null, thread: null, updated: iso(2), next_poll: iso(-1), session: SID(3) };
export const grinds: GrindStatus[] = [grind];
export const releaseRepos: ReleaseRepo[] = [
  { repo: "acme/wasensi-backend", name: "wasensi-backend", head: "staging", base: "master", ahead: 14, prs_waiting: 3, last_release: { pr: 1036, merged_at: iso(20) }, open: "r-20261112T080000Z-bbbbbb", checked_at: iso(1), actions: [] },
  { repo: "acme/wasensi-web", name: "wasensi-web", head: "staging", base: "master", ahead: 6, prs_waiting: 6, last_release: null, open: null, checked_at: iso(1),
    actions: [{ key: "c", label: "Cut release", method: "POST", path: "/api/releases", body: { repo: "acme/wasensi-web" }, toast: "Started release-pr" }] },
];
const R = (p: Partial<Release>): Release => ({ id: "", repo: "acme/wasensi-backend", head: "staging", base: "master", stage: "cut", dry_run: false, pr: null, pr_url: null, thread: null, grind: null,
  cut_session: null, note_session: null, note: null, note_posted_at: null, note_permalink: null, merged_at: null, error: null, dry_run_dir: null, created_at: iso(120), updated_at: iso(20), actions: [], ...p });
export const releases: Release[] = [
  R({ id: "r-20261112T080000Z-bbbbbb", stage: "notify", pr: 1036, pr_url: "https://github.com/acme/wasensi-backend/pull/1036", note, merged_at: iso(20) }),
  R({ id: "r-20261112T090000Z-aaaaaa", repo: "acme/bop-bd", stage: "grind", pr: 1040, grind, cut_session: SID(3) }),
];

export const dispatches: Dispatch[] = [{
  id: "d1a2b3c4d5e6", epic: "acme/wasensi-docs#941", title: "Courier rate cache", state: "running",
  settings: { max: 3, grind: "simple", ci: "wait", auto_merge: false, skip_approval: false, feature_branch: null, base_branch: null, model: null, effort: null, account: null, max_cost: 20 },
  lanes: [
    { key: "acme/wasensi-backend#942", repo: "acme/wasensi-backend", n: 942, title: "Cache table", deps: [], stage: "implementing", pr: null, needs_you: null, held: null, gate: null, skip_reason: null, paused: false, paused_by: null, hold_merge: false, limited_until: null, started_at: null, ended_at: null, session: SID(2), usage: { cost: 1.1, tokens: null, seconds: 600 } },
    { key: "acme/wasensi-backend#943", repo: "acme/wasensi-backend", n: 943, title: "Cache reader", deps: ["acme/wasensi-backend#942"], stage: "queued", pr: null, needs_you: null, held: null, gate: "blocked by #942", skip_reason: null, paused: false, paused_by: null, hold_merge: false, limited_until: null, started_at: null, ended_at: null, session: null, usage: { cost: 0, tokens: null, seconds: 0 } },
  ],
  totals: { lanes: 2, closed: 0, cost: 1.1 }, created_at: Math.floor(now / 1000) - 900, ended_at: null,
  events: [{ at: Math.floor(now / 1000) - 880, lane: null, kind: "start", text: "dispatch started: 2 issues, 3 at most" }, { at: Math.floor(now / 1000) - 870, lane: "acme/wasensi-backend#942", kind: "start", text: "implement-issue started" }],
}];
export const coordinators: Coordinator[] = [{ run: "20261112-coord", repo: "acme/bop-bd", source: "label:payments", destination: "staging", session: SID(4), live: true,
  queue: [{ issue: 455, state: "ok", title: "phpstan" }, { issue: 461, state: "blocked:#455", title: "Rate cache" }], claims: [455], prs: {}, poll: { calls: 12, last: Math.floor(now / 1000), result: "ok", every: 60 }, events: ["#455 verifying", "#458 PR open"] }];
export const panels: Panel[] = [{ id: "p-20261112T090000Z-abcdef", repo: "acme/wasensi-backend", artifact: "/tmp/plan.md", lenses: ["security", "perf"], root_session: SID(1), round: 1, max_rounds: 3, dropped: [], failed: [], state: "running", reason: null, phase: "lenses", lens_sessions: {}, status: { approved: 1, total: 2, lenses: { security: "approve", perf: "waiting" } } }];

export const settings: Settings = {
  claude_label: "work", commands: [{ label: "work", cmd: "claude" }, { label: "personal", cmd: "cc personal" }], default: "work",
  repos: { "acme/wasensi-backend": { auto_grind: true, slack_channel: "dc-supports", reviewers: null, path: "/code/wasensi-backend", grind_path: "github" }, "acme/wasensi-web": { auto_grind: false, slack_channel: "", reviewers: ["copilot"] } },
  slack_channels: [{ id: "C06RSFFRUFM", name: "dc-supports" }], reviewers: [{ id: "copilot", name: "Copilot", slack_id: "", github_login: "copilot" }], active_reviewers: ["copilot"],
  vault_dir: "/Users/me/vault", grind_mode: "deep", use_jev: true, run_model: null, run_effort: null,
  grind_limits: { max_rounds: 10, poll_interval: 60, max_wait: 1500, max_idle_waits: 4, stuck_seen: 2, ci_timeout: 1200, ci_poll: 30 },
  release_note: { channel_name: "dc-supports", channel_id: "C06RSFFRUFM", cc: [{ name: "Ashique", slack_id: "UAY0MVDHT" }, { name: "Najmul", slack_id: "U01012AA4FL" }, { name: "Abir", slack_id: "U067P3ADDDM" }], suffix: "vai" },
  server: { port: 8420, tailscale: true, tailscale_https_port: 443, allow_hosts: [] }, jev_installed: true, bot_label: null,
};
const ev = (key: string, label: string, group: string) => ({ key: key as never, label, group });
export const notify: NotifySettings = {
  matrix: Object.fromEntries(["waiting", "failed", "dispatch", "panel-cap", "pr-ready", "needs-cleanup", "grind-paused", "grind-done", "done", "afk", "release"].map((k) => [k, { browser: true, push: k === "waiting", mac: k !== "done", ntfy: true }])) as NotifySettings["matrix"],
  events: [ev("waiting", "Waiting on you", "Sessions"), ev("failed", "Failed", "Sessions"), ev("done", "Done", "Sessions"), ev("dispatch", "Dispatch needs you", "Dispatch"), ev("panel-cap", "Review panel cap", "Review"),
    ev("pr-ready", "PR ready", "PRs"), ev("needs-cleanup", "Needs cleanup", "PRs"), ev("grind-paused", "Grind paused", "Grind"), ev("grind-done", "Grind done", "Grind"), ev("afk", "Away ended", "Away"), ev("release", "Release", "Release")],
  public_url: "https://mac.tail1234.ts.net", mac: { available: true, notifier: "terminal-notifier", clickable: true }, push: { subscriptions: 1 },
  ntfy_ready: true, server: "https://ntfy.sh", topic: "setu-demo", user: "", token_set: false, password_set: false, env: [],
};
export const reviewCfg: ReviewConfig = {
  max_rounds: 3, default_lenses: ["security", "perf"], lenses: { security: "Look for auth and injection problems", perf: "Look for N+1 and slow paths", tests: "Look for missing tests" },
  shipped: { max_rounds: 3, default_lenses: ["security"], lenses: {} }, overridden: true,
};
export const registry: RegistryStep[] = ([
  ["create-prd", "blubird", "docs", "prd", "Create PRD", "free text, a PRD path"], ["create-tasks", "blubird", "docs", "tasks", "Create tasks", "<PRD path>"],
  ["small-change", "blubird", "repo", "refine", "Small change", "<finding>"], ["refine-issues", "blubird", "issue", "refine", "Refine issues", "<epic | issues>"],
  ["reproduce-bug", "blubird", "issue", "refine", "Reproduce bug", "<issue | symptoms>"], ["implement-issue", "blubird", "issue", "implement", "Implement issue", "<issue | epic>"],
  ["project-coordinator", "blubird", "docs", "implement", "Project coordinator", "<issues link | n>"], ["pr-review", "blubird", "issue", "review", "PR review", "<PR | branch | range> [--fix]"],
  ["peer-review", "setu", "repo", "review", "Peer review", "<artifact>"], ["pr-grind", "setu", "issue", "review", "PR grind", "<PR url>"],
  ["release-pr", "setu", "repo", "release", "Release PR", "[--dry-run]"], ["release-note", "setu", "none", "notify", "Release note", "<pr-url>"],
  ["docs-updater", "blubird", "repo", "ops", "Docs updater", "[full]"], ["security-sweep", "blubird", "docs", "ops", "Security sweep", "[repo name ...]"],
  ["day-end-reconcile", "blubird", "none", "me", "Day-end reconcile", ""],
] as const).map(([id, source, runs_in, stage, label, args_hint]) => ({ id, source, skill: id === "small-change" ? "create-tasks" : id, runs_in, stage, label, args_hint, command: `/${source === "blubird" ? "blubird:" : ""}${id}`, available: true }));
export const openIssues = [
  { number: 1044, title: "CSV export drops the VAT column", labels: ["bug"], updated_at: "2026-11-11T10:00:00Z", draft: false, url: "https://github.com/acme/wasensi-backend/issues/1044" },
  { number: 1013, title: "Batch scheduler", labels: [], updated_at: "2026-11-10T10:00:00Z", draft: false, url: "https://github.com/acme/wasensi-backend/issues/1013" },
];
export const openPRs = [{ number: 1040, title: "Release staging to master", labels: [], updated_at: "2026-11-12T08:00:00Z", draft: false, url: "https://github.com/acme/wasensi-backend/pull/1040" }];
export const vault = { vault: "/Users/me/vault", folders: [{ project: "wasensi", feature: "payouts", path: "wasensi/payouts" }] };
export const prdFile = { repo: PRODUCT, path: "docs/prds/payouts/batches.md", text: "# Merchant payouts v2\n\nStatus: In review\n\n## Goal\nGroup payouts into weekly batches.", sha: "abc", branch: "main" };

export const prds: PRD[] = [
  { product: PRODUCT, module: "payouts", slug: "batches", title: "Merchant payouts v2", status: "In review", path: "docs/prds/payouts/batches.md", label: "payouts/batches", epic: null },
  { product: PRODUCT, module: "kyc", slug: "recheck", title: "KYC re-check", status: "Draft", path: "docs/prds/kyc/recheck.md", label: "kyc/recheck", epic: null },
  { product: PRODUCT, module: "cache", slug: "rates", title: "Rate cache", status: "Approved", path: "docs/prds/cache/rates.md", label: "cache/rates", epic: "acme/wasensi-backend#941" },
  { product: PRODUCT, module: null, slug: "login", title: "Passwordless login", status: "Done", path: "docs/prds/login.md", label: "login", epic: "acme/wasensi-backend#800" },
];

// ---------- features ----------
const fi = (n: number, title: string, state: FeatureIssue["state"], extra: Partial<FeatureIssue> = {}): FeatureIssue => ({
  key: `acme/wasensi-backend#${n}`, repo: "acme/wasensi-backend", n, title, url: `https://github.com/acme/wasensi-backend/issues/${n}`, state,
  refined: state !== "unrefined", bug: false, blockers: [], priority: null, pr: null, session: null, actions: [], ...extra });
const readPrd = (path: string): Action => ({ key: "r", label: "Read PRD", method: "POST", path: "/api/noop", toast: "", open: `#/prd?repo=${PRODUCT}&path=${path}` });
const counts = (issues: FeatureIssue[], done: number) => ({
  open: issues.length, unrefined: issues.filter((i) => i.state === "unrefined").length, ready: issues.filter((i) => i.state === "ready").length,
  review: issues.filter((i) => ["in_review", "conflict", "ci_failed"].includes(i.state)).length, mergeable: issues.filter((i) => i.state === "mergeable").length, done });
const rateIssues = [
  fi(942, "Cache table", "mergeable", { pr: { n: 1050, url: "https://github.com/acme/wasensi-backend/pull/1050", draft: false, ci: "success", review: "approved", conflict: false, sha: "a".repeat(40) },
    actions: [{ key: "m", label: "Merge #1050", method: "POST", path: "/api/pulls/acme/wasensi-backend/1050/merge", body: { sha: "a".repeat(40) }, toast: "Merged #1050", confirm: "Merge PR #1050 into its base now?" }] }),
  fi(943, "Cache reader", "in_progress", { session: SID(2), actions: [{ key: "w", label: "Watch", method: "POST", path: "/api/noop", toast: "", open: `#/sessions/${SID(2)}` }] }),
  fi(944, "Invalidate on rate change", "ready", { actions: [start("i", "Start", "implement-issue", "944", "acme/wasensi-backend", { primary: true })] }),
  fi(945, "Metrics for hit rate", "blocked", { blockers: ["#943"] }),
  fi(946, "Admin toggle", "unrefined", { actions: [start("e", "Refine", "refine-issues", "946", "acme/wasensi-backend")] }),
];
export const featureList: FeatureList = { product: PRODUCT, stale: [], features: [
  { product: PRODUCT, slug: "rates", title: "Rate cache", status: "Approved", path: "docs/prds/cache/rates.md", module: "cache", prd_route: `#/prd?repo=${PRODUCT}&path=docs/prds/cache/rates.md`,
    stage: "building", bay: "you", next: "1 ready to merge.", epic: { key: "acme/wasensi-backend#941", repo: "acme/wasensi-backend", n: 941, title: "Rate cache", url: "https://github.com/acme/wasensi-backend/issues/941" },
    issues: rateIssues, done: [{ key: "acme/wasensi-backend#940", n: 940, title: "Spike: cache store", url: "https://github.com/acme/wasensi-backend/issues/940" }], counts: counts(rateIssues, 1),
    panel: null, dispatch: null, live: 1, sessions: [{ id: SID(2), status: "running", skill: "blubird:implement-issue", title: "#943 Cache reader", started_at: "2026-11-12T08:00:00Z", cost: 2.3 }],
    actions: [rateIssues[0]!.actions[0]!, { key: "d", label: "Run epic", method: "POST", path: "/api/noop", toast: "", open: "#/dispatches?new=acme%2Fwasensi-backend%23941" }, readPrd("docs/prds/cache/rates.md")] },
  { product: PRODUCT, slug: "batches", title: "Merchant payouts v2", status: "In review", path: "docs/prds/payouts/batches.md", module: "payouts", prd_route: `#/prd?repo=${PRODUCT}&path=docs/prds/payouts/batches.md`,
    stage: "review", bay: "running", next: "Peer review round 1 of 3: 1 of 2 lenses approve.", epic: null, issues: [], done: [], counts: counts([], 0),
    panel: { id: "p-20261112T090000Z-abcdef", repo: PRODUCT, artifact: "/code/wasensi-docs/docs/prds/payouts/batches.md", state: "running", round: 1, max_rounds: 3, root_session: SID(1), status: { approved: 1, total: 2 } },
    dispatch: null, live: 0, sessions: [], actions: [{ key: "v", label: "Watch review", method: "POST", path: "/api/noop", toast: "", open: `#/features/batches?product=${PRODUCT}&tab=review` }, readPrd("docs/prds/payouts/batches.md")] },
  { product: PRODUCT, slug: "recheck", title: "KYC re-check", status: "Draft", path: "docs/prds/kyc/recheck.md", module: "kyc", prd_route: `#/prd?repo=${PRODUCT}&path=docs/prds/kyc/recheck.md`,
    stage: "draft", bay: "go", next: "Draft. Run a peer review, or approve it as it is.", epic: null, issues: [], done: [], counts: counts([], 0), panel: null, dispatch: null, live: 0, sessions: [],
    actions: [{ key: "v", label: "Start peer review", method: "POST", path: "/api/noop", toast: "", primary: true, open: `#/features/recheck?product=${PRODUCT}&tab=review` },
      { ...start("p", "Approve without review", "create-prd", "docs/prds/kyc/recheck.md — the team has reviewed it; approve it", PRODUCT), confirm: "Approve this PRD and create its epic?" }, readPrd("docs/prds/kyc/recheck.md")] },
  { product: PRODUCT, slug: "login", title: "Passwordless login", status: "Done", path: "docs/prds/login.md", module: null, prd_route: `#/prd?repo=${PRODUCT}&path=docs/prds/login.md`,
    stage: "shipped", bay: "shipped", next: "Shipped.", epic: null, issues: [], done: [], counts: counts([], 0), panel: null, dispatch: null, live: 0, sessions: [], actions: [readPrd("docs/prds/login.md")] },
] };

export const changesList: ChangesList = { stale: [], pending: [], issues: [
  fi(1044, "CSV export drops the VAT column", "unrefined", { bug: true, priority: "P1", actions: [start("e", "Refine", "refine-issues", "1044", "acme/wasensi-backend")] }),
  fi(1051, "Typo on the payouts page", "ready", { priority: "P3", actions: [start("i", "Start", "implement-issue", "1051", "acme/wasensi-backend", { primary: true })] }),
  fi(1052, "Retry webhook on 502", "ready", { priority: "P2", actions: [start("i", "Start", "implement-issue", "1052", "acme/wasensi-backend", { primary: true })] }),
  fi(1053, "Rename the settings tab", "in_review", { pr: { n: 1060, url: "https://github.com/acme/wasensi-backend/pull/1060", draft: false, ci: "pending", review: "none", conflict: false, sha: "b".repeat(40) } }),
] };
export const issueView: IssueView = { number: 1044, title: "CSV export drops the VAT column", url: "https://github.com/acme/wasensi-backend/issues/1044", state: "OPEN", state_reason: null, is_pr: false, merged: false,
  author: "ashique", created_at: "2026-11-10T10:00:00Z", labels: [{ name: "bug", color: "d73a4a" }], assignees: [], milestone: null, body_html: "<p>Exports since Monday lack the <code>vat</code> column.</p>", comment_count: 1,
  comments: [{ author: "najmul", created_at: "2026-11-11T10:00:00Z", body_html: "<p>Seen on the XLSX too.</p>" }] };
export const prView: PRView = { number: 1060, title: "Rename the settings tab", url: "https://github.com/acme/wasensi-backend/pull/1060", state: "open", conflict: false, head: "issue-1053-rename", base: "staging",
  head_sha: "b".repeat(40), author: "setu-bot", created_at: "2026-11-12T08:00:00Z", body_html: "<p>Closes #1053.</p>", additions: 12, deletions: 4,
  files: [{ path: "web/src/settings.tsx", additions: 12, deletions: 4, status: "modified", patch: null }], commits: [{ sha: "b".repeat(40), message: "rename", author: "setu-bot" }],
  conversation: [{ kind: "review", author: "copilot", at: "2026-11-12T08:30:00Z", state: "COMMENTED", body_html: "<p>Looks fine.</p>" }],
  checks: [{ name: "test", bucket: "pending", link: "https://github.com/acme/wasensi-backend/actions/runs/1" }, { name: "lint", bucket: "green", link: "https://github.com/acme/wasensi-backend/actions/runs/2" }] };
