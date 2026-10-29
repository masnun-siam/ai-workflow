// The app's vocabulary in one place: stages, statuses, tones, board columns, lenses, Start commands.
import type { DeliveryCard, DeliveryColumn, SessionStatus } from '../api/types';

export type Tone = 'plan' | 'build' | 'review' | 'ship' | 'you' | 'bad' | 'muted' | 'away' | 'accent';

export type StageId = 'draft' | 'review' | 'approved' | 'tasks' | 'building' | 'shipped';
export const STAGES: { id: StageId; label: string; tone: Tone }[] = [
  { id: 'draft', label: 'PRD draft', tone: 'plan' },
  { id: 'review', label: 'PRD review', tone: 'plan' },
  { id: 'approved', label: 'Approved', tone: 'plan' },
  { id: 'tasks', label: 'Tasks', tone: 'plan' },
  { id: 'building', label: 'Building', tone: 'build' },
  { id: 'shipped', label: 'Shipped', tone: 'ship' },
];
export const stageIdx = (id: StageId) => STAGES.findIndex((s) => s.id === id);

/** Issue statuses as the UI shows them. `blocked` is a ready/unrefined card with open blockers. */
export type IssueStatus = 'unrefined' | 'blocked' | 'ready' | 'in_progress' | 'draft_pr' | 'in_review' | 'grinding' | 'merged';
export const ISSUE: Record<IssueStatus, { label: string; tone: Tone; color: string }> = {
  unrefined: { label: 'Needs refinement', tone: 'plan', color: 'var(--plan)' },
  blocked: { label: 'Blocked', tone: 'muted', color: 'var(--faint)' },
  ready: { label: 'Ready', tone: 'build', color: 'color-mix(in srgb, var(--build) 45%, var(--line))' },
  in_progress: { label: 'Building', tone: 'build', color: 'var(--build)' },
  draft_pr: { label: 'Draft PR', tone: 'build', color: 'var(--build)' },
  in_review: { label: 'In review', tone: 'review', color: 'var(--review)' },
  grinding: { label: 'Grinding', tone: 'review', color: 'var(--review)' },
  merged: { label: 'Merged', tone: 'ship', color: 'var(--ship)' },
};
export const ISSUE_ORDER: IssueStatus[] = [
  'unrefined', 'blocked', 'ready', 'in_progress', 'draft_pr', 'in_review', 'grinding', 'merged',
];
// The Issues tab's group order: most in need of attention first (FR-13 fixes no order).
export const ATTENTION_ORDER: IssueStatus[] = [
  'in_review', 'grinding', 'in_progress', 'draft_pr', 'ready', 'unrefined', 'blocked', 'merged',
];

/** The status of a delivery card: a blocked card shows as Blocked unless it already has a PR or session. */
export function issueStatus(card: Pick<DeliveryCard, 'column' | 'blocked_by'>): IssueStatus {
  const c = card.column;
  return (c === 'ready' || c === 'unrefined') && card.blocked_by.length > 0 ? 'blocked' : c;
}

// ---- board columns (FR-18): five columns, an issue is in exactly one -------------------------------
export type BoardColumnId = 'refine' | 'ready' | 'building' | 'review' | 'merged';
export const BOARD_COLUMNS: { id: BoardColumnId; label: string; tone: Tone; color: string }[] = [
  { id: 'refine', label: 'Needs refinement', tone: 'plan', color: 'var(--plan)' },
  { id: 'ready', label: 'Ready', tone: 'build', color: 'color-mix(in srgb, var(--build) 45%, var(--line))' },
  { id: 'building', label: 'Building', tone: 'build', color: 'var(--build)' },
  { id: 'review', label: 'In review', tone: 'review', color: 'var(--review)' },
  { id: 'merged', label: 'Merged (7 days)', tone: 'ship', color: 'var(--ship)' },
];
const COLUMN_OF: Record<DeliveryColumn, BoardColumnId> = {
  unrefined: 'refine',
  ready: 'ready',
  in_progress: 'building',
  draft_pr: 'building',
  in_review: 'review',
  grinding: 'review',
  merged: 'merged',
};
export const boardColumn = (c: Pick<DeliveryCard, 'column'>): BoardColumnId => COLUMN_OF[c.column];

// ---- sessions -----------------------------------------------------------------------------------
export const SESS: Record<SessionStatus, { label: string; tone: Tone; live?: boolean }> = {
  queued: { label: 'Queued', tone: 'muted' },
  starting: { label: 'Starting', tone: 'build', live: true },
  running: { label: 'Running', tone: 'build', live: true },
  waiting: { label: 'Needs your answer', tone: 'you' },
  limited: { label: 'Paused for limit', tone: 'review' },
  done: { label: 'Done', tone: 'ship' },
  failed: { label: 'Failed', tone: 'bad' },
  stopped: { label: 'Stopped', tone: 'muted' },
};
export const LIVE: SessionStatus[] = ['queued', 'starting', 'running', 'waiting', 'limited'];
export const RUNNING_NOW: SessionStatus[] = ['starting', 'running', 'waiting'];
export const isLive = (s: SessionStatus) => LIVE.includes(s);

// ---- peer review lenses -------------------------------------------------------------------------
export const LENSES = ['critical', 'ceo', 'cto', 'security', 'qa', 'ux', 'performance'];
export const LENS_NAME: Record<string, string> = {
  critical: 'Critical', ceo: 'CEO', cto: 'CTO', security: 'Security', qa: 'QA', ux: 'UX', performance: 'Performance',
};
export const lensName = (l: string) => LENS_NAME[l] ?? l;

// ---- Start commands (FR-22) ---------------------------------------------------------------------
/** What a command's input is: free text, one ready issue, several issue numbers, an open PR, an approved PRD, a day/range, or nothing. */
export type ArgKind = 'text' | 'issue' | 'issues' | 'pr' | 'prd' | 'day' | 'none';
export interface Command {
  id: string; // skill name, `custom` for a free prompt
  name: string;
  desc: string;
  arg: ArgKind;
  placeholder?: string;
  lenses?: boolean; // offers the peer-review lens picker
  noRepo?: boolean; // can run in the notes vault with no repo yet
}
export interface CommandGroup {
  g: string;
  items: Command[];
}
/** Model and effort for the feature flow's planning starts (PRD, tasks, refine); not the Start dialog's saved choice. */
export const PLAN_RUN = { model: 'opus', effort: 'medium' } as const;

export const COMMANDS: CommandGroup[] = [
  { g: 'Plan', items: [
    { id: 'create-prd', name: 'Write a PRD', desc: 'Claude interviews you about an idea and writes the PRD.', arg: 'text', placeholder: 'Describe the feature: who it is for, what problem it solves…', lenses: true, noRepo: true },
    { id: 'create-tasks', name: 'Break a PRD into tasks', desc: 'Splits an approved PRD into one-PR issues under its epic.', arg: 'prd' },
    { id: 'refine-issues', name: 'Refine issues', desc: 'Writes WHAT, WHY and HOW into each issue so it is ready to build.', arg: 'issues' },
  ] },
  { g: 'Build', items: [
    { id: 'implement-issue', name: 'Implement an issue', desc: 'Takes one refined issue to a ready PR in its own worktree.', arg: 'issue' },
    { id: 'verifier-locally', name: 'Verify changes locally', desc: 'Runs the checks that match the changed files.', arg: 'none' },
  ] },
  { g: 'Review', items: [
    { id: 'pr-review', name: 'Review a PR', desc: 'Evidence-backed review against the issue and the review guide.', arg: 'pr' },
    { id: 'pr-grind', name: 'Grind a PR to approval', desc: 'Loops reviewer bot rounds, fixes findings, pushes, repeats.', arg: 'pr' },
    { id: 'peer-review', name: 'Peer review an artifact', desc: 'Runs the lens panel until every lens approves.', arg: 'text', placeholder: 'Path or description of what to review', lenses: true },
  ] },
  { g: 'Ship', items: [
    { id: 'release-pr', name: 'Open a release PR', desc: 'Staging to master with a release summary and checklist.', arg: 'none' },
  ] },
  { g: 'Capture', items: [
    { id: 'dump', name: 'Dump an idea or bug', desc: 'Files it into your notes vault as a problem statement.', arg: 'text', placeholder: 'Paste anything', noRepo: true },
    { id: 'day', name: 'Plan my day', desc: 'Captures tasks and follow-ups into Todoist, or runs the morning, evening or weekly mode.', arg: 'text', placeholder: 'A task, follow-up or meeting notes (leave empty to plan, shut down or review the week)', noRepo: true },
    { id: 'worklog', name: 'Write a worklog', desc: 'Builds a day’s worklog from GitHub activity.', arg: 'day', noRepo: true },
  ] },
  { g: 'Maintain', items: [
    { id: 'docs-updater', name: 'Update docs', desc: 'Brings docs in line with recent changes.', arg: 'none' },
    { id: 'faq-updater', name: 'Update FAQ', desc: 'Writes and updates the user guide and FAQ from the code', arg: 'text', placeholder: 'One question per line. Options: full, --lang en,bn, --videos <playlist URL>' },
    { id: 'repo-bootstrap', name: 'Bootstrap repo', desc: 'Makes a repo ready for agents and this workflow, one PR per phase.', arg: 'text', placeholder: 'Optional: a phase (audit, decide, constitution, guides, gates, docs) and the bootstrap issue number' },
    { id: 'sync-from-wasensi', name: 'Sync from Wasensi', desc: 'Ports upstream skill and guide changes.', arg: 'none' },
    { id: 'skill-feedback', name: 'Skill feedback', desc: 'Turns feedback into skill and guide edits, or mines closed PRs for learnings.', arg: 'text', placeholder: 'Feedback on a skill or guide, or reconcile to mine the learning logs of closed PRs' },
    { id: 'custom', name: 'Custom prompt', desc: 'Anything else. Runs with permissions skipped.', arg: 'text', placeholder: 'Prompt for Claude', lenses: true },
  ] },
];
export const COMMAND_LIST: Command[] = COMMANDS.flatMap((g) => g.items);
export const COMMAND: Record<string, Command> = Object.fromEntries(COMMAND_LIST.map((c) => [c.id, c]));

// ---- inbox groups (FR-7) ------------------------------------------------------------------------
export const INBOX_GROUPS = [
  { id: 'block', label: 'Blocking everything' },
  { id: 'answer', label: 'Answer Claude' },
  { id: 'decide', label: 'Decide' },
  { id: 'fix', label: 'Fix' },
  { id: 'setup', label: 'Set up' },
  { id: 'wait', label: 'Waiting (nothing to do)' },
] as const;
