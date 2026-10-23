// Which dispatch owns an epic or an issue, for the pages around dispatches (feature header, issue rows,
// the Grinding switch). Reads the polled /api/dispatches; no extra request.
import { useDispatches } from '../api/hooks';
import type { Dispatch, Lane } from '../api/types';
import { ACTIVE, counts } from './vocab';

const live = (d: Dispatch) => d.state === 'running' || d.state === 'paused';
const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

/** The running (or paused) dispatch of `repo#epic`, with its progress; null when there is none. */
export function useEpicDispatch(repo: string, epic: number | null) {
  const all = useDispatches().data?.dispatches ?? [];
  const d = epic ? all.find((x) => live(x) && same(x.epic, `${repo}#${epic}`)) : undefined;
  return d ? { d, c: counts(d) } : null;
}

/** issue number -> its lane in a live dispatch, for one repo. A queued lane counts: the dispatch will start it. */
export function useOwnedIssues(repo: string): Map<number, { d: Dispatch; l: Lane }> {
  const all = useDispatches().data?.dispatches ?? [];
  const m = new Map<number, { d: Dispatch; l: Lane }>();
  for (const d of all.filter(live))
    for (const l of d.lanes)
      if (same(l.repo, repo) && (ACTIVE.includes(l.stage) || l.stage === 'queued')) m.set(l.n, { d, l });
  return m;
}
