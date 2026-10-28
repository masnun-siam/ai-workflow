import { useMemo, useState } from 'react';
import { useDelivery, usePlanning } from '../api/hooks';
import { useRefining, useStarter } from '../board/actions';
import { BoardStatus } from '../board/BoardStatus';
import { Button, EmptyState } from '../components';
import { NewDispatchDialog } from '../dispatch/NewDispatchDialog';
import { useOwnedIssues } from '../dispatch/useOwner';
import { CaptureBar, priorityName } from '../features/CaptureBar';
import { SmallChangesTab } from '../features/SmallChangesTab';
import { SMALL_CHANGE_LOCK, useSmallChangeSessions } from '../features/smallChange';
import '../features/features.css';
import { joinFeatures, outsideFeatures, snapshotsReady, type FeatureIssue } from '../lib/features';
import { PLAN_RUN } from '../lib/vocab';
import { usePanel } from '../panels/PanelContext';
import { useRepo } from '../shell/useRepo';

const PRIO = ['critical', 'high', 'medium', 'low', ''] as const;
const COLS = [
  { id: 'refine', label: 'Needs refining', has: (i: FeatureIssue) => i.column === 'unrefined' },
  { id: 'ready', label: 'Ready', has: (i: FeatureIssue) => i.column === 'ready' },
  { id: 'flight', label: 'In flight', has: (i: FeatureIssue) => i.column !== 'unrefined' && i.column !== 'ready' && i.column !== 'merged' },
] as const;
const prio = (i: FeatureIssue) => (PRIO as readonly string[]).includes(i.priority ?? '') ? (i.priority ?? '') : '';
const byPrio = (a: FeatureIssue, b: FeatureIssue) => PRIO.indexOf(prio(a) as never) - PRIO.indexOf(prio(b) as never) || b.n - a.n;
const shade = (n: number) => (n === 0 ? '' : n < 3 ? 'l1' : n < 10 ? 'l2' : 'l3');

type Filter = { p: string; c: string } | null;

export function SmallChangesPage() {
  const { repo } = useRepo();
  const plan = usePlanning(repo);
  const del = useDelivery(repo);
  const panel = usePanel();
  const starter = useStarter();
  const refining = useRefining(repo);
  const owned = useOwnedIssues(repo);
  const pending = useSmallChangeSessions(repo);
  const [filter, setFilter] = useState<Filter>(null);
  const [picked, setPicked] = useState<number[]>([]);
  const [dispatching, setDispatching] = useState(false);
  const [allReady, setAllReady] = useState(false);
  const [allRefine, setAllRefine] = useState(false);

  const features = useMemo(() => joinFeatures(plan.data?.prds ?? [], del.data?.lanes ?? []), [plan.data, del.data]);
  const outside = useMemo(() => outsideFeatures(features, del.data?.lanes ?? []), [features, del.data]);
  const open = outside.filter((i) => i.column !== 'merged');
  const ready = open.filter((i) => i.column === 'ready' && !i.blocked_by.length && !owned.has(i.n)).sort(byPrio);
  const toRefine = open.filter((i) => i.column === 'unrefined').sort(byPrio);
  const loaded = plan.isSuccess && !del.isPending && snapshotsReady(plan.data, del.data);
  const shown = filter ? open.filter((i) => prio(i) === filter.p && COLS.find((c) => c.id === filter.c)!.has(i)) : outside;
  const run = useMemo(() => ready.filter((i) => picked.includes(i.n)).map((i) => ({ n: i.n, title: i.title })), [ready, picked]);
  const togglePick = (n: number) => setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : [...p, n]));
  const refine = (n: number) => starter.startBoard({ repo, skill: 'refine-issues', arg: String(n), via: 'headless', ...PLAN_RUN }, { nav: false });

  return (
    <div className="content-inner">
      <CaptureBar repo={repo} initial="small" />
      <header>
        <h1 className="display">Small changes</h1>
        <p className="lede">{loaded ? `${open.length} open issue${open.length === 1 ? '' : 's'} outside any feature. ${ready.length} ${ready.length === 1 ? 'is' : 'are'} ready to run now.` : 'Bugs and one-issue changes, outside any feature.'}</p>
      </header>
      <BoardStatus meta={del.data} />
      {del.isError && !del.data ? (
        <EmptyState icon="alert" title="Issues unavailable" actions={<Button onClick={() => del.refetch()}>Retry</Button>}>{del.error.message}</EmptyState>
      ) : !loaded ? (
        <div className="stack" aria-busy="true"><p className="muted" role="status">Loading issues…</p><div className="skel" style={{ height: 300 }} /></div>
      ) : (
        <>
          <div className="sc-top">
            <section className="pane mx" aria-labelledby="mx-h">
              <h2 id="mx-h" style={{ fontSize: 16 }}>Where they stand</h2>
              <div className="mx-g" style={{ gridTemplateColumns: `96px repeat(${COLS.length}, minmax(0,1fr))` }}>
                <span />
                {COLS.map((c) => <b key={c.id}>{c.label}</b>)}
                {PRIO.map((p) => (
                  <MxRow key={p || 'none'} p={p} open={open} filter={filter} setFilter={setFilter} />
                ))}
              </div>
              <span className="muted" style={{ fontSize: 12 }}>
                {filter ? <>Showing {priorityName(filter.p).toLowerCase()}, {COLS.find((c) => c.id === filter.c)!.label.toLowerCase()}. <button type="button" className="linkish" style={{ textDecoration: 'underline' }} onClick={() => setFilter(null)}>Show all</button></> : `Darker means more. Click a number to filter the list. ${outside.length - open.length} merged are not counted.`}
              </span>
            </section>

            <section className="readyp" aria-labelledby="rd-h">
              <div className="ready-h">
                <h2 id="rd-h">Ready to run</h2>
                <p>Refined, unblocked, not in a dispatch yet</p>
                <Button sm disabled={!run.length} onClick={() => setDispatching(true)}>{run.length ? `Run ${run.length} as a dispatch` : 'Pick issues to run'}</Button>
              </div>
              {ready.length ? (
                <div className="stack" style={{ gap: 6 }}>
                  {(allReady ? ready : ready.slice(0, 5)).map((i) => (
                    <label key={i.n} className="ready-r">
                      <input type="checkbox" checked={picked.includes(i.n)} onChange={() => togglePick(i.n)} aria-label={`Run #${i.n}`} />
                      <span className="n">#{i.n}</span>
                      <span className="t" title={i.title}>{i.title}</span>
                      <span className="p">{priorityName(prio(i))}</span>
                    </label>
                  ))}
                  {ready.length > 5 ? <button type="button" className="linkish" style={{ color: 'inherit', opacity: 0.9, padding: '6px 12px 0', fontSize: 13 }} onClick={() => setAllReady(!allReady)}>{allReady ? 'Show fewer' : `${ready.length - 5} more ready`}</button> : null}
                </div>
              ) : <p style={{ margin: 0, opacity: 0.9 }}>Nothing is ready. Refine an issue below to make it runnable.</p>}
            </section>
          </div>

          {toRefine.length ? (
            <section className="stack" style={{ gap: 14 }} aria-labelledby="rf-h">
              <h2 id="rf-h" className="sec-h">Needs refining first <span className="n">{toRefine.length}</span></h2>
              <div className="rgrid">
                {(allRefine ? toRefine : toRefine.slice(0, 8)).map((i) => (
                  <article key={i.n} className={`pane rcard${prio(i) === 'critical' ? ' crit' : ''}`} onClick={() => panel.open({ kind: 'issue', repo, n: i.n })}>
                    <div className="row" style={{ gap: 8 }}>
                      <span className="mono muted" style={{ fontSize: 12.5 }}>#{i.n}</span>
                      {prio(i) ? <span className={`tag ${prio(i)}`}>{priorityName(prio(i))}</span> : null}
                    </div>
                    <span className="rt">{i.title}</span>
                    <div onClick={(e) => e.stopPropagation()}>
                      {refining.has(i.n) ? <span className="muted" style={{ fontSize: 13 }}>Refining…</span> : <Button sm aria-label={`Refine #${i.n}`} title={pending.length ? SMALL_CHANGE_LOCK : undefined} disabled={starter.pending || !!pending.length} onClick={() => void refine(i.n)}>Refine</Button>}
                    </div>
                  </article>
                ))}
              </div>
              {toRefine.length > 8 ? <button type="button" className="linkish" style={{ alignSelf: 'flex-start', fontSize: 13, textDecoration: 'underline' }} onClick={() => setAllRefine(!allRefine)}>{allRefine ? 'Show fewer' : `Show all ${toRefine.length}`}</button> : null}
            </section>
          ) : null}

          <section className="stack" style={{ gap: 14 }} aria-labelledby="all-h">
            <h2 id="all-h" className="sec-h">{filter ? 'Filtered issues' : 'All issues'} <span className="n">{shown.length}</span></h2>
            <SmallChangesTab key={repo} repo={repo} issues={shown} pending={filter ? [] : pending} />
          </section>
        </>
      )}
      <NewDispatchDialog open={dispatching} onOpenChange={(o) => { setDispatching(o); if (!o) setPicked([]); }} issues={run} />
    </div>
  );
}

function MxRow({ p, open, filter, setFilter }: { p: string; open: FeatureIssue[]; filter: Filter; setFilter: (f: Filter) => void }) {
  return (
    <>
      <span className={p === 'critical' ? 'crit' : ''}>{priorityName(p)}</span>
      {COLS.map((c) => {
        const n = open.filter((i) => prio(i) === p && c.has(i)).length;
        const on = filter?.p === p && filter.c === c.id;
        return (
          <button
            key={c.id}
            type="button"
            className={`mx-c ${p === 'critical' && n ? 'hot' : shade(n)}`}
            aria-pressed={on}
            aria-label={`${priorityName(p)}, ${c.label.toLowerCase()}: ${n}`}
            disabled={!n}
            onClick={() => setFilter(on ? null : { p, c: c.id })}
          >{n}</button>
        );
      })}
    </>
  );
}
