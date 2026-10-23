// Dispatch words: lane stages, their tones and progress, and the lane's one-line status.
import type { Dispatch, DispatchState, Lane, LaneStage } from '../api/types';
import type { Tone } from '../lib/vocab';

export const STAGE: Record<LaneStage, { label: string; tone: Tone; step: number }> = {
  queued: { label: 'Waiting', tone: 'muted', step: 0 },
  implementing: { label: 'Building', tone: 'build', step: 1 },
  grinding: { label: 'Grinding', tone: 'review', step: 2 },
  merge_gate: { label: 'Merging', tone: 'review', step: 3 },
  conflict_fix: { label: 'Fixing conflicts', tone: 'review', step: 3 },
  awaiting_merge: { label: 'Your merge', tone: 'you', step: 3 },
  followups: { label: 'Wrapping up', tone: 'ship', step: 4 },
  closed: { label: 'Done', tone: 'ship', step: 5 },
  skipped: { label: 'Skipped', tone: 'muted', step: 0 },
};
/** The steps a lane walks, for the stepper and the list's progress bar. */
export const STEPS = ['Build', 'Grind', 'Merge', 'Wrap up', 'Done'];
export const ACTIVE: LaneStage[] = ['implementing', 'grinding', 'merge_gate', 'conflict_fix', 'awaiting_merge', 'followups'];

export const DSTATE: Record<DispatchState, { label: string; tone: Tone; live?: boolean }> = {
  running: { label: 'Running', tone: 'build', live: true },
  paused: { label: 'Paused', tone: 'review' },
  done: { label: 'Finished', tone: 'ship' },
  cancelled: { label: 'Cancelled', tone: 'muted' },
};

/** What a lane needs or waits on, most urgent first; null when it is just working. */
export function laneNote(l: Lane): { text: string; tone: Tone } | null {
  if (l.needs_you) return { text: l.needs_you, tone: 'you' };
  if (l.held) return { text: l.held, tone: 'bad' };
  if (l.limited_until && l.limited_until * 1000 > Date.now()) return { text: 'Claude usage limit', tone: 'away' };
  if (l.paused) return { text: 'Paused', tone: 'review' };
  if (l.stage === 'skipped') return { text: l.skip_reason ?? 'Skipped', tone: 'muted' };
  if (l.stage === 'merge_gate' && l.gate) return { text: l.gate, tone: 'muted' };
  if (l.stage === 'awaiting_merge') return { text: l.hold_merge ? 'Merge held' : 'Waiting for your merge', tone: 'you' };
  return null;
}

export const needsYou = (l: Lane) => !!(l.needs_you || l.held || l.stage === 'awaiting_merge');

export function counts(d: Pick<Dispatch, 'lanes'>) {
  const c = { total: d.lanes.length, closed: 0, active: 0, queued: 0, skipped: 0, you: 0 };
  for (const l of d.lanes) {
    if (l.stage === 'closed') c.closed++;
    else if (l.stage === 'skipped') c.skipped++;
    else if (l.stage === 'queued') c.queued++;
    else c.active++;
    if (needsYou(l)) c.you++;
  }
  return c;
}

/** Dependency depth per lane key: 0 for no deps inside the dispatch. Cycles are cut, never loop. */
export function levels(lanes: Pick<Lane, 'key' | 'deps'>[]): Record<string, number> {
  const by = new Map(lanes.map((l) => [l.key, l]));
  const out: Record<string, number> = {};
  const depth = (k: string, seen: Set<string>): number => {
    if (k in out) return out[k];
    if (seen.has(k)) return 0;
    seen.add(k);
    const deps = (by.get(k)?.deps ?? []).filter((d) => by.has(d));
    const v = deps.length ? 1 + Math.max(...deps.map((d) => depth(d, seen))) : 0;
    out[k] = v;
    return v;
  };
  for (const l of lanes) depth(l.key, new Set());
  return out;
}

export const issueNo = (key: string) => key.replace(/^.*#/, '#');
export const epicNo = (epic: string) => epic.replace(/^.*#/, '');
export const ghIssue = (repo: string, n: number) => `https://github.com/${repo}/issues/${n}`;
export const ghPr = (repo: string, n: number) => `https://github.com/${repo}/pull/${n}`;

export function secs(s: number): string {
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ${m % 60}m` : `${Math.floor(h / 24)}d ${h % 24}h`;
}

/** What a lane needs from you, as one action. */
export type LaneAsk = 'merge' | 'open' | 'retry';

/** One plain sentence for what the lane is doing now, and the action when it needs you. */
export function nowLine(l: Lane, lanes: Pick<Lane, 'key' | 'stage'>[], nowMs = Date.now()): { text: string; tone: Tone; ask?: LaneAsk } {
  if (l.needs_you)
    return l.needs_you === 'waiting on you'
      ? { text: 'Asked you a question', tone: 'you', ask: l.session || l.tab ? 'open' : 'retry' }
      : { text: sentence(l.needs_you), tone: 'you', ask: 'retry' };
  if (l.held) return { text: sentence(l.held), tone: 'bad', ask: 'retry' };
  if (l.stage === 'awaiting_merge') return l.hold_merge ? { text: 'You held the merge', tone: 'muted' } : { text: `PR #${l.pr} is ready for your merge`, tone: 'you', ask: 'merge' };
  if (l.limited_until && l.limited_until * 1000 > nowMs) return { text: 'Paused by the Claude usage limit', tone: 'away' };
  if (l.paused) return { text: 'Paused by you', tone: 'review' };
  switch (l.stage) {
    case 'queued': {
      const open = l.deps.filter((d) => (lanes.find((x) => x.key === d)?.stage ?? 'closed') !== 'closed');
      return { text: open.length ? `Starts after ${open.map(issueNo).join(' and ')}` : 'Starts when a slot frees up', tone: 'muted' };
    }
    case 'implementing':
      return { text: l.pr ? `Getting PR #${l.pr} ready` : 'Implementing the issue', tone: 'build' };
    case 'grinding':
      return { text: `Working through review on PR #${l.pr}`, tone: 'review' };
    case 'merge_gate':
      return { text: GATE[l.gate ?? ''] ?? `Merging PR #${l.pr}`, tone: 'review' };
    case 'conflict_fix':
      return { text: `Resolving conflicts on PR #${l.pr}`, tone: 'review' };
    case 'followups':
      return { text: 'Closing the issue and cleaning up', tone: 'ship' };
    case 'closed':
      return { text: l.pr ? `PR #${l.pr} merged` : 'Done', tone: 'ship' };
    default:
      return { text: l.skip_reason === 'needs refine' ? 'Skipped: refine it first' : sentence(l.skip_reason ?? 'Skipped'), tone: 'muted' };
  }
}
const GATE: Record<string, string> = {
  'CI is not green': 'Waiting for CI to pass',
  'no approving review': 'Waiting for an approving review',
  'waiting for green CI (defer)': 'Waiting for green CI (defer)',
  'grind is not done': 'Waiting for the grind to finish',
};
const sentence = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

/** The activity feed in plain words: "queued -> implementing" reads "started building". */
export function eventText(e: { kind: string; text: string }): string {
  const m = /^(\w+) -> (\w+)(.*)$/.exec(e.text);
  if (e.kind === 'stage' && m) {
    const to = m[2] as LaneStage;
    const said: Partial<Record<LaneStage, string>> = {
      implementing: 'started building', grinding: 'went to the grind', merge_gate: 'is ready to merge',
      conflict_fix: 'is fixing merge conflicts', awaiting_merge: 'is waiting for your merge',
      followups: 'merged; wrapping up', closed: 'is done', queued: 'is waiting again', skipped: 'was skipped',
    };
    return (said[to] ?? `is ${STAGE[to]?.label.toLowerCase() ?? to}`) + (m[3] ?? '');
  }
  if (e.kind === 'started') return `Dispatch started: ${e.text}`;
  if (e.kind === 'lane') return e.text === 'joined the dispatch' ? 'joined the dispatch' : `you chose ${e.text}`;
  return sentence(e.text);
}
