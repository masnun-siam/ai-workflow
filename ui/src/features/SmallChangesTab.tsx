import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRefining, useStarter } from '../board/actions';
import { useListSelection } from '../components';
import { NewDispatchDialog } from '../dispatch/NewDispatchDialog';
import { useOwnedIssues } from '../dispatch/useOwner';
import type { FeatureIssue } from '../lib/features';
import { routes } from '../lib/routes';
import { PLAN_RUN } from '../lib/vocab';
import { usePanel } from '../panels/PanelContext';
import { useRepo } from '../shell/useRepo';
import { IssueTable, orderedIssues } from './IssuesTab';
import { PendingRows } from './PendingRows';
import { PickBar } from './PickBar';
import { SMALL_CHANGE_LOCK, type PendingChange } from './smallChange';

const pickable = (i: FeatureIssue) => i.column === 'unrefined' || i.column === 'ready';

/** Open issues outside any feature, grouped by status, under the live small-change sessions. */
export function SmallChangesTab({ repo, issues, pending }: { repo: string; issues: FeatureIssue[]; pending: PendingChange[] }) {
  const starter = useStarter();
  const owned = useOwnedIssues(repo);
  const refining = useRefining(repo);
  const [picked, setPicked] = useState<number[]>([]);
  const [dispatching, setDispatching] = useState(false);
  const toggle = (n: number) => setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : [...p, n]));
  const navigate = useNavigate();
  const { link } = useRepo();
  const panel = usePanel();
  const pendingKey = (p: PendingChange) => `p:${p.id}`;
  const selection = useListSelection({
    keys: [...pending.map(pendingKey), ...orderedIssues(issues).map((i) => String(i.n))],
    onOpen: (k) => (k.startsWith('p:') ? navigate(link(routes.session(k.slice(2)))) : panel.open({ kind: 'issue', repo, n: Number(k) })),
    panelTarget: (k) => (k.startsWith('p:') ? null : { kind: 'issue', repo, n: Number(k) }),
    reset: repo,
  });
  const lock = pending.length ? SMALL_CHANGE_LOCK : undefined;

  // Derived from the board on every render, so a picked issue that closes, refines or joins a dispatch moves or drops out.
  const live = picked.map((n) => issues.find((i) => i.n === n)).filter((i): i is FeatureIssue => !!i && !owned.has(i.n) && !refining.has(i.n));
  const toRefine = live.filter((i) => i.column === 'unrefined').map((i) => i.n);
  // The dialog resets when its list changes identity, so keep one identity while the picked refined issues stay the same.
  const runKey = JSON.stringify(live.filter((i) => i.column === 'ready').map((i) => ({ n: i.n, title: i.title })));
  const toRun = useMemo(() => JSON.parse(runKey) as { n: number; title: string }[], [runKey]);

  return (
    <div className="stack">
      <PendingRows pending={pending} selection={selection} />
      {toRefine.length || toRun.length ? (
        <PickBar
          refine={toRefine.length}
          run={toRun.length}
          busy={starter.pending}
          refineLock={lock}
          onRefine={async () => { const id = await starter.startBoard({ repo, skill: 'refine-issues', arg: toRefine.join(' '), via: 'headless', ...PLAN_RUN }); if (id !== null) setPicked([]); }}
          onRun={() => setDispatching(true)}
          onClear={() => setPicked([])}
        />
      ) : null}
      {issues.length ? (
        <IssueTable issues={issues} repo={repo} picked={picked} onPick={toggle} canPick={pickable} lockRefine={lock} selection={selection} />
      ) : pending.length ? null : (
        <p className="muted">Nothing here. Describe a bug or small change above to start one.</p>
      )}
      <NewDispatchDialog open={dispatching} onOpenChange={setDispatching} issues={toRun} repo={repo} />
    </div>
  );
}
