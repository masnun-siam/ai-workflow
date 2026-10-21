// Hand-written contracts for every endpoint the UI uses. Existing shapes come from run-engine/ui_*.py;
// the ones marked NEW follow docs/prds/ui-rewrite.md ("API"). Fields the server may omit are optional.

export type RepoSlug = string; // owner/name, or local/<name> for a repo with no GitHub remote

// ---- sessions -------------------------------------------------------------------------------------
export type SessionStatus = 'queued' | 'starting' | 'running' | 'waiting' | 'limited' | 'done' | 'failed' | 'stopped';

export interface QuestionOption {
  label: string;
  description?: string;
}
export interface Question {
  question: string;
  header?: string | null;
  multiSelect: boolean;
  options: QuestionOption[];
  recommended?: string | null; // label of the option tagged "(Recommended)"
  allowFreeText: boolean;
}
export interface PendingQuestion {
  id: string; // the round id POST /answer wants as round_id
  status?: string;
  allowFreeText?: boolean;
  questions: Question[];
}
export interface SessionLink {
  owner: string;
  repo: string;
  issue: number;
}
export interface PanelStatus {
  approved: number;
  total: number;
  round: number;
  max_rounds?: number;
  state: string; // running | approved | cap | failed ...
  reason?: string | null;
  lenses: Record<string, 'approve' | 'changes' | 'waiting' | 'failed' | string>;
  role?: 'root' | 'lens' | string | null;
  lens?: string | null;
  panel?: string;
}
export interface Session {
  id: string;
  command: string;
  repo: string | null; // checkout path for UI-started sessions
  link: SessionLink | string | null;
  session_id: string | null;
  outcome: SessionStatus; // the session's status
  cost: number | null;
  tokens: { input?: number; cached?: number; output?: number } | null;
  started_at: string;
  ended_at: string | null;
  waiting: boolean;
  pending_question: PendingQuestion | null;
  error: string | null;
  resumed_fresh: boolean | null;
  note: string | null;
  terminal_handoff: unknown;
  pending_answer: unknown;
  queued_prompt: string | null;
  claude_cmd: string | null;
  limit_resets_at: number | null; // epoch seconds
  limit_type: string | null;
  auto_resume: boolean | null;
  no_repo: boolean;
  vault_folder: string | null;
  peer_review: PanelStatus | null;
  repo_path: string | null;
  resume_command: string | null;
  /** NEW: GET /api/sessions rows may carry the slug and what the session is for. */
  slug?: string;
  [k: string]: unknown;
}
export interface Limit {
  limited_until?: number;
  warning?: { type?: string; utilization?: number };
}
export interface UsageWindow {
  pct: number;
  resets_at: string | null;
}
export interface AccountUsage {
  five_hour?: UsageWindow;
  seven_day?: UsageWindow;
  at?: number;
  error?: string | null;
}
export interface AfkState {
  active: boolean;
  until: number | null; // epoch seconds
  started: number | null;
  decisions: number;
  held: number;
  summary: null | { started: number; ended: number | null; log: unknown[]; held: number };
}
export interface GhStatus {
  ok: boolean;
  login?: string | null;
  error?: string | null;
}
export interface SessionsResponse {
  sessions: Session[];
  limits: Record<string, Limit>;
  usage: Record<string, AccountUsage>;
  afk: AfkState;
  gh?: GhStatus; // NEW
}

export type StreamEvent = Record<string, unknown> & { type?: string };
export interface StreamResponse {
  events: StreamEvent[];
  offset: number;
}

// ---- boards ---------------------------------------------------------------------------------------
export type PrdStatus = 'Draft' | 'In review' | 'Approved';
export type PlanningColumn = 'draft' | 'in_review' | 'approved' | 'tasks_filed' | 'refined';
export interface PanelRef extends PanelStatus {
  id: string;
  root_session?: string | null;
}
export interface PlanningPrd {
  slug: string;
  title: string;
  status: PrdStatus;
  path: string;
  abs_path: string;
  column: PlanningColumn;
  pr: { n: number; url: string } | null;
  epic: number | null;
  issues: number;
  refined: number;
  unrefined: number[];
  children: { n: number; title: string; refined: boolean }[];
  panel: PanelRef | null;
  mtime?: number; // last update, when the server sends it
}
export interface BoardMeta {
  repo: RepoSlug;
  stale: boolean;
  fetched_at: number | null;
  error?: string | null;
  retry_at?: number | null;
}
export interface PlanningResponse extends BoardMeta {
  prds: PlanningPrd[];
}

export type DeliveryColumn = 'unrefined' | 'ready' | 'in_progress' | 'draft_pr' | 'in_review' | 'grinding' | 'merged';
export type ReviewDecision = 'approved' | 'changes_requested' | 'review_required' | 'none';
export interface Grind {
  state: 'running' | 'idle' | 'paused';
  round?: number;
  max_rounds?: number;
  reason?: string | null;
}
export interface DeliveryCard {
  n: number;
  title: string;
  column: DeliveryColumn;
  priority: string | null;
  blocked_by: number[];
  pr: { n: number; draft: boolean; ci: string | null; url: string; review?: ReviewDecision } | null;
  session: { id: string; status: SessionStatus } | null;
  grind?: Grind | null;
  needs_cleanup: null | { uncommitted: string[]; unpushed: string[] };
  last_failed?: boolean;
}
export interface DeliveryLane {
  epic: number | null;
  title: string;
  autopilot: boolean; // "auto-build" in the UI
  cap: number;
  running: number;
  cards: DeliveryCard[];
}
export interface DeliveryResponse extends BoardMeta {
  cap: number;
  running: number;
  auto_grind: boolean;
  lanes: DeliveryLane[];
}

// ---- inbox (NEW) ----------------------------------------------------------------------------------
export type InboxGroup = 'block' | 'answer' | 'decide' | 'fix' | 'setup' | 'wait';
interface InboxBase {
  key: string;
  group: InboxGroup;
  repo: RepoSlug | null;
  at: number | string | null;
}
export type InboxItem =
  | (InboxBase & { type: 'gh_auth'; error?: string })
  | (InboxBase & {
      type: 'question';
      session_id: string;
      command: string;
      link: SessionLink | string | null;
      questions: PendingQuestion | Question[]; // the pending round, or just its questions (see questionsOf)
      process_alive: boolean;
      round_id?: string;
    })
  | (InboxBase & {
      type: 'review_cap';
      prd_path: string;
      panel: string;
      round: number;
      max_rounds: number;
      note?: string | null;
    })
  | (InboxBase & { type: 'review_approved'; prd_path: string; panel: string })
  | (InboxBase & {
      type: 'pr_ready';
      pr: number;
      issue: number | null;
      title: string;
      reviewer?: string | null;
      checks?: number | { total: number; passed: number } | null;
    })
  | (InboxBase & { type: 'grind_paused'; pr: number; issue: number | null; round: number; reason: string })
  | (InboxBase & { type: 'session_failed'; session_id: string; command: string; link: SessionLink | string | null; error: string })
  | (InboxBase & { type: 'needs_cleanup'; issue: number; uncommitted: string[]; unpushed: string[] })
  | (InboxBase & { type: 'repo_unpublished'; slug: string; path: string })
  | (InboxBase & { type: 'limited'; session_id: string; command?: string; account: string; resets_at: number; auto_resume: boolean | null })
  | (InboxBase & { type: 'queued'; session_id: string; command?: string; reason: string });
export interface InboxResponse {
  items: InboxItem[];
  afk: AfkState;
  gh: GhStatus;
  stale?: RepoSlug[];
}

// ---- repos, settings ------------------------------------------------------------------------------
export interface Repo {
  slug: RepoSlug;
  name: string;
  path: string;
  github?: boolean | string | null;
}
export interface ReposResponse {
  repos: Repo[];
  can_browse: boolean;
  scan_roots: string[];
}
export interface ClaudeCommand {
  label: string;
  cmd: string;
  builtin?: boolean;
}
export interface RepoSettings {
  auto_grind: boolean;
  autopilot_cap: number;
  slack_channel: string;
}
export interface Settings {
  commands: ClaudeCommand[];
  default: string;
  repos?: Record<RepoSlug, RepoSettings>;
  autopilot?: Record<RepoSlug, number[]> | Record<RepoSlug, Record<string, boolean>>;
  vault_dir?: string;
  claude_label?: string;
  [k: string]: unknown;
}
export interface NotifySettings {
  server: string;
  topic: string;
  user: string;
  public_url: string;
  token_set: boolean;
  password_set: boolean;
  env: string[];
}
export interface ReviewSettings {
  max_rounds: number;
  default_lenses: string[];
  lenses: Record<string, string>;
  edited?: string[];
  /** The plugin's own defaults, to mark a prompt as edited. */
  shipped?: { max_rounds: number; default_lenses: string[]; lenses: Record<string, string> };
  /** True when a saved override exists (Reset removes it). */
  overridden?: boolean;
  [k: string]: unknown;
}
export interface PeerReviewOffers {
  default: string[];
  max_rounds: number;
  kinds: Record<string, string[]>;
}
export interface VaultFolder {
  project: string;
  feature: string | null;
  path: string;
}
export interface VaultFolders {
  vault: string;
  folders: VaultFolder[];
}
export interface VaultPrd {
  exists: boolean;
  status?: string;
  title?: string;
  path?: string;
}
export interface CleanupItem {
  key: string;
  label: string;
  repo: string;
  flags: string[];
}

// ---- issues, pull requests, PRDs ------------------------------------------------------------------
export interface GhUser {
  login: string;
  avatar?: string | null;
  [k: string]: unknown;
}
export interface IssueDetail {
  number: number;
  title: string;
  url: string;
  state: 'open' | 'closed' | string;
  state_reason: string | null;
  is_pr: boolean;
  author: GhUser | null;
  created_at: string;
  labels: { name: string; color: string }[];
  assignees: (GhUser | null)[];
  milestone: string | null;
  body_html: string;
  comment_count: number;
  comments: { author: GhUser | null; created_at: string; body_html: string }[];
}
export interface PrFile {
  filename?: string;
  path?: string;
  status?: string;
  additions?: number;
  deletions?: number;
  patch?: string | null;
  [k: string]: unknown;
}
export interface PrDetail {
  number: number;
  title: string;
  url: string;
  state: 'open' | 'merged' | 'closed' | 'draft' | string;
  author: GhUser | null;
  created_at: string;
  head: string;
  base: string;
  labels: { name: string; color: string }[];
  assignees: (GhUser | null)[];
  milestone: string | null;
  body_html: string;
  additions: number;
  deletions: number;
  file_count: number;
  files: PrFile[];
  commit_count: number;
  commits: { sha: string; subject: string; author: string | GhUser | null; at: string }[];
  conversation: Record<string, unknown>[];
  checks: Record<string, unknown>[] | Record<string, unknown>;
  [k: string]: unknown;
}
export interface OpenItem {
  number: number;
  title: string;
  labels: string[];
  updated_at: string;
  draft: boolean;
  url: string | null;
}
export interface PrdFile {
  text: string;
  path?: string;
  sha?: string; // NEW
  [k: string]: unknown;
}

// ---- request bodies / small responses -------------------------------------------------------------
export type StartVia = 'headless' | 'herdr';
/** POST /api/sessions: start a session. `command` is the slash command text, or `text` for a free prompt. */
export interface SessionStartBody {
  repo?: string; // registered slug, or a checkout path
  command?: string; // e.g. "implement-issue"
  args?: string; // the command's argument text
  text?: string; // custom prompt (runs with permissions skipped)
  issue?: number;
  claude_cmd?: string; // an account label from Settings
  no_repo?: boolean; // run in the notes vault (create-prd, dump, custom)
  vault_folder?: string; // 05-Work/<Project>[/<Feature>]
  batch?: string; // groups a worklog range
  peer_review?: string[]; // lens names
  [k: string]: unknown;
}
/** POST /api/start: the board's one-click starts (refine, create-tasks, implement-issue, pr-grind, ...). */
export interface BoardStartBody {
  repo: string;
  skill: string;
  arg: string | number | (string | number)[];
  via?: StartVia;
  lenses?: string[];
}
/** POST /api/start: a public session, or for herdr `{session: null, via: 'herdr', tab}` (NEW). */
export type BoardStartResponse = Partial<Session> & { session?: string | null; via?: StartVia; tab?: string };
/** 409 body from a duplicate start (and rerun): the session already running. */
export interface DuplicateError {
  error: string;
  id?: string;
  href?: string;
}
/** POST /api/sessions/<id>/answer: one entry per question index, exactly one of labels | other. */
export interface AnswerBody {
  round_id: string;
  answers: Record<string, { labels: string[] } | { other: string }>;
}

// ---- PR / issue / PRD shapes as the server really sends them (ui_pr.py, ui_issue.py) ----------------
export interface PrCheck { name: string | null; link: string | null; bucket: 'green' | 'red' | 'pending' }
export interface PrConvItem { kind: 'comment' | 'review'; verdict?: string; author: string; at: string | null; body_html: string }
export interface PrFileRow { name: string; from?: string | null; status?: string; additions: number; deletions: number; patch: string | null; patch_cut?: boolean }
export interface PrCommitRow { sha: string; subject: string; author: string; at: string }

/** POST /api/repos/scan: what it registered, and the clones it skipped as duplicates. */
export interface ScanResult {
  added: { slug: string; path: string }[];
  duplicates: { slug: string; path: string }[];
  repos: Repo[];
}
