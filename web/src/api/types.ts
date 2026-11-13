// Transcribed from docs/setu/API.md section 4. JSON field names are exact; keep in sync with the contract.

// ---------- common ----------
export type ISO = string;            // RFC 3339 UTC "2026-11-12T09:30:00Z"
export type Epoch = number;          // unix seconds
export type Slug = string;           // "owner/name"
export type IssueKey = string;       // "owner/name#123"
export type Link = { owner: string; repo: string; issue: number } | null;
export type ApiError = { error: string; id?: string; href?: string; [k: string]: unknown };
export type Tone = "" | "c-w" | "c-q" | "c-o" | "c-b";   // prototype tag colours: warn, query/live, ok, bad

/** Server-built action. The UI renders the button and on press calls fetch(method, path, body).
 *  2xx → show `toast`; if `clears`, optimistically drop the row/need. Non-2xx → show ApiError.error. */
export type Action = {
  key: string;                 // one keyboard letter, unique within the item
  label: string;
  method: "POST" | "PUT" | "DELETE";
  path: string;                // absolute "/api/..."
  body?: unknown;
  toast: string;
  primary?: boolean;
  clears?: boolean;
  confirm?: string;            // if set, ask with this text first
  open?: string;               // instead of a fetch: UI navigation ("#/sessions/<id>", "#/prd?repo=..&path=..") or an https URL (new tab)
};

// ---------- sessions ----------
export type SessionStatus = "starting"|"running"|"waiting"|"limited"|"queued"|"done"|"failed"|"stopped";
export type Option = { label: string; description: string; preview?: string };
export type Question = { header: string; question: string; multiSelect: boolean; allowFreeText: boolean;
  recommended: string | null; options: Option[] };
export type Round = { id: string; status: "pending"; allowFreeText: boolean; held?: boolean;
  answerer?: string | null; risk?: { p: number | null; unknown?: boolean }; questions: Question[] };
export type Answer = { labels: string[] } | { other: string } | { none: true };
export type Answers = Record<string /* "0".."n-1" */, Answer>;
export type Tokens = { input: number; cached: number; output: number };

export type Session = {
  id: string; step: string | null; skill: string | null;   // skill "blubird:implement-issue" | "pr-grind" | null (free text)
  kind: string | null;          // "grind" | "release" | "release-note" | "lens" | "panel-root" | "lane" | "coordinator" | null
  title: string;                // issue/PR title from the snapshot when linked, else command's first line ≤120
  command: string; repo: Slug | null; repo_path: string | null; link: Link;
  session_id: string | null; status: SessionStatus;
  model: string | null; effort: string | null; cost: number | null; tokens: Tokens | null;
  started_at: ISO; ended_at: ISO | null; duration_s: number | null;  // ended_at||now − started_at
  waiting: boolean; pending_question: Round | null;
  error: string | null; note: string | null; pending_answer: string | null; queued_prompt: string | null;
  account: string;              // label (or the raw cmd when no longer saved)
  limit_resets_at: Epoch | null; limit_type: string | null; auto_resume: boolean | null;
  hold: boolean; no_repo: boolean; vault_folder: string | null; dismissed: boolean;
  panel: { id: string; role: "root" | "lens"; lens: string | null; state: PanelState } | null;
  dispatch: { id: string; lane: IssueKey } | null;
  hooks: number;                // count of hook events seen (§TranscriptEvent kind "hook")
  resume_command: string | null;
  stalled: string | null;       // why the run stopped without finishing (headless idle guard); null when it did not stall
};
export type SessionStats = { today_count: number; today_cost: number; month_count: number; month_cost: number };

export type StartRequest = {
  step?: string;                // registry step id (§9). Exactly one of step | text.
  text?: string;                // free prompt, ≤32000, non-blank, no NUL, not starting "-"
  args?: string;                // appended to the step command; no NUL; for the steps in §9.2, grammar-checked
  repo?: Slug | string;         // registered slug or absolute checkout path. Required unless runs_in "none" or no_repo
  product?: Slug;               // docs repo slug; enough for runs_in "docs"
  issue?: number;               // link; positive int
  no_repo?: boolean; vault_folder?: string;   // vault run (custom text only), S§5.4
  account?: string;             // saved label
  pin_account?: boolean; batch?: string; model?: Model; effort?: Effort;
  lenses?: string[];            // also open a peer-review panel on this run (S§5.4)
  guard?: boolean;              // card guards: live duplicate, dispatch lane owns, open blockers (implement-issue), 30 s identical start
  force?: boolean;              // skip the blocker guard only
};
export type Model = "opus" | "sonnet" | "haiku";
export type Effort = "low" | "medium" | "high" | "xhigh" | "max";

export type TranscriptEvent =
  | { kind: "text"; text: string }
  | { kind: "tool"; name: string; input: unknown }
  | { kind: "result"; cost: number | null; is_error: boolean; text: string | null; tokens: Tokens | null }
  | { kind: "hook"; name: string; event: string; text: string; blocked: boolean };
// hook sources: stream lines type=system with subtype starting "hook" (name=hook_name, event=hook_event, text=output|stdout ≤500);
// guard_ask → {name:"claude-md-guard", event:"PreToolUse", text:"<tool> <path> denied", blocked:true};
// prompt_blocked → {name:"mask-secrets", event:"UserPromptSubmit", text:reason, blocked:true}.
export type Transcript = { events: TranscriptEvent[]; offset: number };

export type Limit = { limited_until?: Epoch; warning?: { type: string; utilization: number } };
export type Meter = { pct: number; resets_at: ISO | null } | null;
export type AccountUsage = { label: string; cmd: string; five_hour: Meter; seven_day: Meter; at: Epoch | null; error: string | null; limit: Limit };

// ---------- status ----------
export type Status = {
  version: string; boot_id: string;
  blubird: Blubird; gh: { ok: boolean; login: string; error: string };
  usage: AccountUsage[]; away: Away; migrated: boolean;
  poller: { remaining: number | null; reset_at: ISO | null };
};
export type Blubird = { installed: boolean; version: string; latest: string; update_available: boolean;
  install_path: string; marketplace: string; skills: string[]; hooks: string[]; busy: "" | "installing" | "updating"; error: string };

// ---------- repos / products ----------
export type Repo = { slug: Slug; path: string; product: Slug | null };
export type ProductRepo = { name: string; role: string; repo: Slug; path: string; cloned: boolean; conflict?: Slug };
export type Product = { docs_repo: Slug; name: string; path: string; repos: ProductRepo[]; error?: string };
// name = docs repo's repos.json "product" key if present, else the docs repo name without "-docs"/"-wiki"
export type PRD = { product: Slug; module: string | null; slug: string; title: string;
  status: "Draft" | "In review" | "Approved" | "Done"; path: string; label: string; epic: IssueKey | null };
export type PRDFile = { repo: Slug; path: string; text: string; sha: string; branch: string };

// ---------- GitHub popups (shapes as G§1.2) ----------
export type IssueView = { number: number; title: string; url: string; state: string; state_reason: string | null; is_pr: boolean;
  merged: boolean; author: string; created_at: ISO; labels: { name: string; color: string }[]; assignees: string[];
  milestone: string | null; body_html: string; comment_count: number;
  comments: { author: string; created_at: ISO; body_html: string }[] };
export type PRView = { number: number; title: string; url: string; state: "open"|"closed"|"merged"|"draft"; conflict: boolean;
  head: string; base: string; head_sha: string; author: string; created_at: ISO; body_html: string; additions: number; deletions: number;
  files: { path: string; additions: number; deletions: number; status: string; patch: string | null; patch_cut?: boolean }[];
  commits: { sha: string; message: string; author: string }[];
  conversation: { kind: "comment" | "review"; author: string; at: ISO; state?: string; body_html: string }[];
  checks: { name: string; bucket: "green" | "red" | "pending"; link: string }[] };
export type OpenItem = { number: number; title: string; labels: string[]; updated_at: ISO; draft: boolean; url?: string };

// ---------- River ----------
export type StageId = "prd" | "tasks" | "refine" | "implement" | "review" | "release" | "notify";
export type Card = {
  id: string;                   // stable: "prd:<slug>" | "epic:<key>" | "issue:<key>" | "pr:<key>" | "session:<id>" | "release:<id>" | "repo:<slug>" | "coord:<run>"
  stage: StageId; title: string; meta: string; tag: string; tone: Tone;
  need: boolean; need_kind: "Question" | "Approval" | "Failed" | "Release" | "Decide" | null;
  live: boolean; skill: string; repo: string;     // repo display name (last slug segment)
  log: string[];                // ≤8 lines, newest last
  ask: { session_id: string; round: Round } | null;   // UI answers via POST /api/sessions/{id}/answer
  note: string | null;          // release note text when need_kind "Release"
  links: { issue?: string; pr?: string; session?: string; prd?: string };
  actions: Action[];
};
export type River = { product: Slug; stale: Slug[]; fetched_at: ISO | null;
  stages: { id: StageId; name: string; skills: string; hot: boolean; cards: Card[] }[] };

// ---------- Inbox ----------
export type InboxGroup = "block" | "answer" | "decide" | "fix" | "setup" | "wait";
export type InboxItem = {
  key: string; group: InboxGroup; type: InboxType; kind: string;  // kind = display tag ("Question","Approval","Failed","Release",...)
  title: string; repo: Slug | null; at: ISO | null; urgency: number | null;
  session_id?: string; round?: Round; note?: string; detail?: string[];
  links: { issue?: string; pr?: string; session?: string; prd?: string };
  actions: Action[];
};
export type InboxType = "gh_auth" | "blubird_missing" | "question" | "prd_approval" | "session_failed" | "limited" | "queued"
  | "session_stalled" | "review_cap" | "review_approved" | "grind_paused" | "needs_cleanup" | "pr_conflict" | "pr_ready" | "release_note"
  | "dispatch_needs" | "dispatch_stalled" | "dispatch_held" | "dispatch_merge" | "dispatch_limited" | "dispatch_done" | "away_summary" | "repo_unpublished";
export type InboxList = { items: InboxItem[]; stale: Slug[]; count: number /* items not in group "wait" */ };

// ---------- Releases ----------
export type ReleaseStage = "cut" | "grind" | "merge" | "notify" | "done" | "skipped" | "failed" | "dry_run";
export type Release = { id: string; repo: Slug; head: string; base: string; stage: ReleaseStage; dry_run: boolean;
  pr: number | null; pr_url: string | null; thread: string | null; grind: GrindStatus | null;
  cut_session: string | null; note_session: string | null; note: string | null; note_posted_at: ISO | null;
  note_permalink: string | null; merged_at: ISO | null; error: string | null; dry_run_dir: string | null;
  created_at: ISO; updated_at: ISO; actions: Action[] };
export type ReleaseRepo = { repo: Slug; name: string; head: string; base: string; ahead: number | null; prs_waiting: number | null;
  last_release: { pr: number; merged_at: ISO } | null; open: string | null /* release id in flight */; checked_at: ISO | null; actions: Action[] };

// ---------- Ops / Me ----------
export type SessionBrief = { id: string; status: SessionStatus; started_at: ISO; ended_at: ISO | null; cost: number | null };
export type OpsRow = { step: string; label: string; scope: "each repo" | "docs repo" | "any repo"; summary: string;
  targets: { repo: Slug; last: SessionBrief | null; note: string }[]; actions: Action[] };
export type Ops = { product: Slug; rows: OpsRow[] };
export type Me = { day_end: { date: string; reconciled: boolean; missing_days: number; last: SessionBrief | null };
  weekly: { week: number; drafted: boolean; last: SessionBrief | null };
  usage: AccountUsage[]; cost: SessionStats; actions: Action[] };

// ---------- grind ----------
export type GrindState = "none" | "idle" | "running" | "paused" | "approved" | "done";
export type GrindStatus = { repo: Slug; pr: number; state: GrindState; mode: "deep" | "simple" | null; rounds: number;
  reason: string | null; thread: string | null; updated: ISO | null; next_poll: ISO | null; session: string | null };

// ---------- dispatch (W§2; public view) ----------
export type LaneStage = "queued"|"implementing"|"grinding"|"merge_gate"|"conflict_fix"|"awaiting_merge"|"followups"|"closed"|"skipped";
export type DispatchSettings = { max: number; grind: "off"|"simple"|"full"; ci: "wait"|"defer"|"ignore"; auto_merge: boolean;
  skip_approval: boolean; feature_branch: string | null; base_branch: string | null; model: string | null;
  effort: Effort | null; account: string | null; max_cost: number | null };
export type Lane = { key: IssueKey; repo: Slug; n: number; title: string; deps: IssueKey[]; stage: LaneStage; pr: number | null;
  needs_you: string | null; held: string | null; gate: string | null; skip_reason: string | null; paused: boolean;
  paused_by: "dispatch" | null; hold_merge: boolean; limited_until: Epoch | null; started_at: Epoch | null;
  ended_at: Epoch | null; session: string | null; usage: { cost: number; tokens: Tokens | null; seconds: number };
  stranded?: string | null; skipped_deps?: IssueKey[]; unblocked?: IssueKey[];
  stalled: string | null /* the lane's session stopped without finishing; needs_you is null then */ };
export type Dispatch = { id: string; epic: IssueKey | null; issues?: IssueKey[]; title: string;
  state: "running" | "paused" | "done" | "cancelled"; settings: DispatchSettings; lanes: Lane[];
  totals: { lanes: number; closed: number; cost: number }; created_at: Epoch; ended_at: Epoch | null;
  events?: { at: Epoch; lane: IssueKey | null; kind: string; text: string }[] };
export type DispatchPlan = { title: string; waves: IssueKey[][]; lanes: { key: IssueKey; title: string; refined: boolean; deps: IssueKey[] }[]; warnings: string[] };
export type Coordinator = { run: string /* run dir basename */; repo: Slug; source: string; destination: string; session: string | null;
  live: boolean; queue: { issue: number; state: string; title: string }[]; claims: number[]; prs: Record<string, unknown>;
  poll: { calls: number; last: Epoch; result: string; every: number } | null; events: string[] /* last 20 lines of events.log */ };

// ---------- away (W§3) ----------
export type Away = { active: boolean; until: Epoch | null; started: Epoch | null; decisions: number; held: number;
  summary: { started: Epoch; ended: Epoch; held: number; log: AwayLog[] } | null };
export type AwayLog = { at: Epoch; kind: "answer" | "held" | "retry"; sid: string; link: Link; repo: Slug | null; command: string;
  question: string; picked: string; id?: string; risk?: number; by?: "recommended" | "opus";
  questions?: (Question & { picked: string[]; why: string })[]; answerer?: string; cost?: number; changed?: boolean; reason?: string };

// ---------- peer review (W§5) ----------
export type PanelState = "running" | "approved" | "cap reached" | "failed";
export type Panel = { id: string; repo: Slug; artifact: string; lenses: string[]; root_session: string | null; round: number;
  max_rounds: number; dropped: string[]; failed: string[]; state: PanelState; reason: string | null;
  phase: "waiting_root" | "lenses" | "root" | "done"; lens_sessions: Record<string, string>;
  status: { approved: number; total: number; lenses: Record<string, "failed" | "approve" | "changes" | "waiting"> } };
export type ReviewOffers = { default: string[]; max_rounds: number; kinds: Record<string, string[]> };
export type ReviewConfig = { max_rounds: number; default_lenses: string[]; lenses: Record<string, string>;
  shipped: { max_rounds: number; default_lenses: string[]; lenses: Record<string, string> }; overridden: boolean };

// ---------- settings (on-disk names; D13) ----------
export type RepoSettings = { auto_grind: boolean; slack_channel: string; reviewers: string[] | null;
  release_head?: string; release_base?: string;                 // default "staging" → "master"
  /* GET only: */ path?: string | null; grind_path?: "slack" | "github" | null; channel_invalid?: boolean };
export type Settings = {
  claude_label: string; commands: { label: string; cmd: string; builtin?: boolean }[]; default: string;
  repos: Record<Slug, RepoSettings>;
  slack_channels: { id: string; name: string }[];
  reviewers: { id: string; name: string; slack_id: string; github_login: string }[]; active_reviewers: string[];
  vault_dir: string | null; grind_mode: "deep" | "simple"; use_jev: boolean;
  run_model: Model | null; run_effort: Effort | null;
  grind_limits: { max_rounds: number; poll_interval: number; max_wait: number; max_idle_waits: number;
    stuck_seen: number; ci_timeout: number; ci_poll: number };     // defaults 10, 60, 1500, 4, 2, 1200, 30
  release_note: { channel_name: string; channel_id: string; cc: { name: string; slack_id: string }[]; suffix: string };
    // default {"dc-supports","C06RSFFRUFM",[Ashique UAY0MVDHT, Najmul U01012AA4FL, Abir U067P3ADDDM],"vai"}
  server: { port: number; tailscale: boolean; tailscale_https_port: 443 | 8443 | 10000; allow_hosts: string[] };
  /* GET only: */ jev_installed?: boolean; bot_label?: string | null;
};
export type NotifySettings = { matrix: Record<NotifyEvent, { browser: boolean; push: boolean; mac: boolean; ntfy: boolean }>;
  events: { key: NotifyEvent; label: string; group: string }[]; public_url: string;
  mac: { available: boolean; notifier: string; clickable: boolean }; push: { subscriptions: number };
  ntfy_ready: boolean; server: string; topic: string; user: string; token_set: boolean; password_set: boolean; env: string[] };
export type NotifyEvent = "waiting"|"failed"|"dispatch"|"panel-cap"|"pr-ready"|"needs-cleanup"|"grind-paused"|"grind-done"|"done"|"afk"|"release";
export type PushSubscription = { endpoint: string; keys: { p256dh: string; auth: string } };

// ---------- vault ----------
export type VaultFolder = { project: string; feature: string | null; path: string };
export type VaultSuggestion = { project: string; feature: string; new_project: boolean; new_feature: boolean; why: string };
export type VaultPRD = { exists: boolean; status: string | null; title: string | null; folder: string };

// ---------- features (old aiw Features; GET /api/features?product=) ----------
export type FeatureStage = "draft" | "review" | "approved" | "tasks" | "building" | "shipped";
export type FeatureIssueState = "unrefined" | "blocked" | "ready" | "in_progress" | "waiting" | "failed" | "in_review" | "mergeable" | "conflict" | "ci_failed" | "dispatch";
export type FeatureIssue = { key: IssueKey; repo: Slug; n: number; title: string; url: string; state: FeatureIssueState; refined: boolean; bug: boolean;
  blockers: string[]; priority: string | null; pr: { n: number; url: string; draft: boolean; ci: string; review: string; conflict: boolean; sha: string } | null;
  session: string | null; actions: Action[] };
export type Feature = {
  product: Slug; slug: string; title: string; status: PRD["status"]; path: string; module: string | null; prd_route: string;
  stage: FeatureStage; bay: "you" | "go" | "running" | "shipped"; next: string;
  epic: { key: IssueKey; repo: Slug; n: number; title: string; url: string } | null;
  issues: FeatureIssue[]; done: { key: IssueKey; n: number; title: string; url: string }[];
  counts: { open: number; unrefined: number; ready: number; review: number; mergeable: number; done: number };
  panel: { id: string; repo: Slug; artifact: string; state: PanelState; round: number; max_rounds: number; root_session: string | null; status: { approved: number; total: number } } | null;
  dispatch: { id: string; state: string; lanes: number; closed: number; needs: number } | null;
  live: number; sessions: { id: string; status: SessionStatus; skill: string; title: string; started_at: ISO; cost: number }[];
  actions: Action[];
};
export type FeatureList = { product: Slug; stale: Slug[]; features: Feature[] };
export type ChangesList = { stale: Slug[]; issues: FeatureIssue[]; pending: Feature["sessions"] };
export type CleanupItem = { key: string; label: string; repo: string; flags: string[] };
