// Dispatch words: lane stages, their tones and progress, and the lane's one-line status.
import type { Dispatch, DispatchState, Lane, LaneStage } from '../api/types';
import type { Tone } from '../lib/vocab';

export const STAGE: Record<LaneStage, { label: string; tone: Tone; step: number }> = {
  queued: { label: 'Queued', tone: 'muted', step: 0 },
  implementing: { label: 'Implementing', tone: 'build', step: 1 },
  grinding: { label: 'Grinding', tone: 'review', step: 2 },
  merge_gate: { label: 'Merge gate', tone: 'review', step: 3 },
  conflict_fix: { label: 'Fixing conflicts', tone: 'review', step: 3 },
  awaiting_merge: { label: 'Ready to merge', tone: 'you', step: 3 },
  followups: { label: 'Followups', tone: 'ship', step: 4 },
  closed: { label: 'Done', tone: 'ship', step: 5 },
  skipped: { label: 'Skipped', tone: 'muted', step: 0 },
};
/** The steps a lane walks, for the stepper and the list's progress bar. */
export const STEPS = ['Implement', 'Grind', 'Merge', 'Followups', 'Done'];
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
