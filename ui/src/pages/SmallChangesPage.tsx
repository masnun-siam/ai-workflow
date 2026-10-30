import { useMemo, useState, type ReactNode } from 'react';
import { useDeliveryAll, useDelivery, useDispatches, usePlanning, usePlanningAll, useRepos } from '../api/hooks';
import type { BoardEntry, DeliveryResponse, PlanningResponse } from '../api/types';
import { useRefining, useStarter } from '../board/actions';
import { BoardStatus } from '../board/BoardStatus';
import { Button, EmptyState } from '../components';
import { NewDispatchDialog } from '../dispatch/NewDispatchDialog';
import { ownedIssues, useOwnedIssues } from '../dispatch/useOwner';
import { CaptureBar, priorityName } from '../features/CaptureBar';
import { SmallChangesTab } from '../features/SmallChangesTab';
import { SMALL_CHANGE_LOCK, useSmallChangeSessions } from '../features/smallChange';
import '../features/features.css';
import { joinFeatures, outsideFeatures, snapshotsReady, type FeatureIssue } from '../lib/features';
import { PLAN_RUN } from '../lib/vocab';
import { usePanel } from '../panels/PanelContext';
import { RepoSelect } from '../shell/RepoSelect';
import { useRepo } from '../shell/useRepo';
import { useRepoFilter } from '../shell/useRepoFilter';

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
const matches = (f: NonNullable<Filter>, i: FeatureIssue) => prio(i) === f.p && COLS.find((c) => c.id === f.c)!.has(i);
const lede = (open: number, ready: number) => `${open} open issue${open === 1 ? '' : 's'} outside any feature. ${ready} ${ready === 1 ? 'is' : 'are'} ready to run now.`;

/** The page: All repos by default; `?only=` narrows it to today's single-repo page. */
export function SmallChangesPage() {
  const { repo } = useRepo();
  const { only, setOnly } = useRepoFilter();
  const repos = useRepos().data?.repos ?? [];
  const picker = <RepoSelect repos={repos} value={only} onChange={setOnly} label="Repo filter" width={180} extrasBefore={[{ value: '', label: 'All repos' }]} />;
  return only ? <RepoBoard key={only} repo={only} picker={picker} /> : <AllRepos repo={repo} picker={picker} />;
}

function Head({ picker, lede: text }: { picker: ReactNode; lede: string }) {
  return (
    <header>
      <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h1 className="display">Small changes</h1>
        {picker}
      </div>
      <p className="lede">{text}</p>
    </header>
  );
}

/** One repo's page: its board, picks and "Run N as a dispatch". */
function RepoBoard({ repo, picker }: { repo: string; picker: ReactNode }) {
  const plan = usePlanning(repo);
  const del = useDelivery(repo);
  const owned = useOwnedIssues(repo);
  const pending = useSmallChangeSessions(repo);
  const [filter, setFilter] = useState<Filter>(null);
  const [picked, setPicked] = useState<number[]>([]);
  const [dispatching, setDispatching] = useState(false);

  const features = useMemo(() => joinFeatures(plan.data?.prds ?? [], del.data?.lanes ?? []), [plan.data, del.data]);
  const outside = useMemo(() => outsideFeatures(features, del.data?.lanes ?? []), [features, del.data]);
  const open = outside.filter((i) => i.column !== 'merged');
  const ready = open.filter((i) => i.column === 'ready' && !i.blocked_by.length && !owned.has(i.n)).sort(byPrio);
  const toRefine = open.filter((i) => i.column === 'unrefined').sort(byPrio);
  const loaded = plan.isSuccess && !del.isPending && snapshotsReady(plan.data, del.data);
  const shown = filter ? open.filter((i) => matches(filter, i)) : outside;
  const run = useMemo(() => ready.filter((i) => picked.includes(i.n)).map((i) => ({ n: i.n, title: i.title })), [ready, picked]);
  const togglePick = (n: number) => setPicked((p) => (p.includes(n) ? p.filter((x) => x !== n) : [...p, n]));

  return (
    <div className="content-inner">
      <CaptureBar repo={repo} initial="small" />
      <Head picker={picker} lede={loaded ? lede(open.length, ready.length) : 'Bugs and one-issue changes, outside any feature.'} />
      <BoardStatus meta={del.data} />
      {del.isError && !del.data ? (
        <EmptyState icon="alert" title="Issues unavailable" actions={<Button onClick={() => del.refetch()}>Retry</Button>}>{del.error.message}</EmptyState>
      ) : !loaded ? (
        <Loading />
      ) : (
        <>
          <div className="sc-top">
            <Matrix open={open} merged={outside.length - open.length} filter={filter} setFilter={setFilter} />
            <section className="readyp" aria-labelledby="rd-h">
              <div className="ready-h">
                <h2 id="rd-h">Ready to run</h2>
                <p>Refined, unblocked, not in a dispatch yet</p>
                <Button sm disabled={!run.length} onClick={() => setDispatching(true)}>{run.length ? `Run ${run.length} as a dispatch` : 'Pick issues to run'}</Button>
              </div>
              <ReadyRows items={ready} picked={picked} onPick={togglePick} />
            </section>
          </div>

          {toRefine.length ? (
            <section className="stack" style={{ gap: 14 }} aria-labelledby="rf-h">
              <h2 id="rf-h" className="sec-h">Needs refining first <span className="n">{toRefine.length}</span></h2>
              <RefineCards repo={repo} items={toRefine} />
            </section>
          ) : null}

          <section className="stack" style={{ gap: 14 }} aria-labelledby="all-h">
            <h2 id="all-h" className="sec-h">{filter ? 'Filtered issues' : 'All issues'} <span className="n">{shown.length}</span></h2>
            <SmallChangesTab key={repo} repo={repo} issues={shown} pending={filter ? [] : pending} />
          </section>
        </>
      )}
      <NewDispatchDialog open={dispatching} onOpenChange={(o) => { setDispatching(o); if (!o) setPicked([]); }} issues={run} repo={repo} />
    </div>
  );
}

const Loading = () => <div className="stack" aria-busy="true"><p className="muted" role="status">Loading issues…</p><div className="skel" style={{ height: 300 }} /></div>;

/** One watched repo's slice of the All repos page. `note` is set while its data is loading or stale. */
type Group = { repo: string; name: string; note: string | null; outside: FeatureIssue[]; open: FeatureIssue[]; ready: FeatureIssue[]; toRefine: FeatureIssue[] };

/** A meta-only entry (its body failed to build) counts as empty; its note says why. */
const prdsOf = (e?: BoardEntry<PlanningResponse>) => (e && 'prds' in e ? e.prds : []);
const lanesOf = (e?: BoardEntry<DeliveryResponse>) => (e && 'lanes' in e ? e.lanes : []);
function noteOf(p: BoardEntry<PlanningResponse>, d?: BoardEntry<DeliveryResponse>): string | null {
  const error = p.error || d?.error;
  const loading = p.fetched_at == null || d?.fetched_at == null;
  if (!loading && !error && !p.stale && !d?.stale) return null;
  return `${loading ? 'Still loading…' : 'GitHub data is stale.'}${error ? ` ${error}` : ''}`;
}

/** Every watched repo: one grid across them, and Ready, Needs refining and the issue list grouped by repo. */
function AllRepos({ repo, picker }: { repo: string; picker: ReactNode }) {
  const plan = usePlanningAll(true);
  const del = useDeliveryAll(true);
  const names = useRepos().data?.repos ?? [];
  const dispatches = useDispatches().data?.dispatches ?? [];
  const [filter, setFilter] = useState<Filter>(null);
  const [picked, setPicked] = useState<{ repo: string; n: number }[]>([]);
  const [dispatching, setDispatching] = useState(false);

  const groups: Group[] = useMemo(
    () => (plan.data?.repos ?? []).map((p) => {
      const d = del.data?.repos.find((x) => x.repo.toLowerCase() === p.repo.toLowerCase());
      const lanes = lanesOf(d);
      const outside = outsideFeatures(joinFeatures(prdsOf(p), lanes), lanes);
      const open = outside.filter((i) => i.column !== 'merged');
      const owned = ownedIssues(dispatches, p.repo);
      return {
        repo: p.repo,
        name: names.find((r) => r.slug.toLowerCase() === p.repo.toLowerCase())?.name ?? p.repo,
        note: noteOf(p, d),
        outside,
        open,
        ready: open.filter((i) => i.column === 'ready' && !i.blocked_by.length && !owned.has(i.n)).sort(byPrio),
        toRefine: open.filter((i) => i.column === 'unrefined').sort(byPrio),
      };
    }),
    [plan.data, del.data, names, dispatches],
  );
  const open = groups.flatMap((g) => g.open);
  const ready = groups.reduce((n, g) => n + g.ready.length, 0);
  const merged = groups.reduce((n, g) => n + g.outside.length - g.open.length, 0);
  const refine = groups.filter((g) => g.toRefine.length);
  const failed = (plan.isError && !plan.data) || (del.isError && !del.data);
  const loaded = !!plan.data && !!del.data;
  const isPicked = (g: Group, n: number) => picked.some((p) => p.n === n && p.repo.toLowerCase() === g.repo.toLowerCase());
  // Derived from the current Ready lists on every render, so a pick that is no longer ready drops out and can free the other repos.
  const live = groups.flatMap((g) => g.ready.filter((i) => isPicked(g, i.n)).map((i) => ({ repo: g.repo, n: i.n, title: i.title })));
  const pickRepo = live[0]?.repo;
  const pickName = groups.find((g) => g.repo === pickRepo)?.name;
  const note = pickRepo ? `Picks are from ${pickName}. Clear them to pick from another repo.` : undefined;
  // The dialog resets when its list changes identity, so keep one identity while the picks stay the same.
  const runKey = JSON.stringify(live.map(({ n, title }) => ({ n, title })));
  const run = useMemo(() => JSON.parse(runKey) as { n: number; title: string }[], [runKey]);
  const togglePick = (g: Group, n: number) => setPicked((p) => (isPicked(g, n) ? p.filter((x) => !(x.n === n && x.repo.toLowerCase() === g.repo.toLowerCase())) : [...p, { repo: g.repo, n }]));

  return (
    <div className="content-inner">
      <CaptureBar repo={repo} initial="small" pickRepo />
      <Head picker={picker} lede={loaded ? lede(open.length, ready) : 'Bugs and one-issue changes, outside any feature.'} />
      <BoardStatus />
      {failed ? (
        <EmptyState icon="alert" title="Issues unavailable" actions={<Button onClick={() => { void plan.refetch(); void del.refetch(); }}>Retry</Button>}>{(plan.error ?? del.error)?.message}</EmptyState>
      ) : !loaded ? (
        <Loading />
      ) : !groups.length ? (
        <EmptyState icon="alert" title="No repo opened recently. Pick one in the filter." />
      ) : (
        <>
          <div className="sc-top">
            <Matrix open={open} merged={merged} filter={filter} setFilter={setFilter} />
            <section className="readyp" aria-labelledby="rd-h">
              <div className="ready-h">
                <h2 id="rd-h">Ready to run</h2>
                <p>Refined, unblocked, not in a dispatch yet</p>
                <Button sm disabled={!run.length} onClick={() => setDispatching(true)}>{run.length ? `Run ${run.length} as a dispatch` : 'Pick issues to run'}</Button>
              </div>
              {note ? <p className="muted" role="status" style={{ margin: 0 }}>{note}</p> : null}
              {ready ? groups.filter((g) => g.ready.length).map((g) => (
                <div key={g.repo} className="stack" style={{ gap: 6 }}>
                  <GroupHead g={g} />
                  <ReadyRows items={g.ready} picked={live.filter((p) => p.repo === g.repo).map((p) => p.n)} onPick={(n) => togglePick(g, n)} lock={pickRepo && pickRepo !== g.repo ? note : undefined} />
                </div>
              )) : <p style={{ margin: 0, opacity: 0.9 }}>Nothing is ready. Refine an issue below to make it runnable.</p>}
            </section>
          </div>

          {refine.length ? (
            <section className="stack" style={{ gap: 14 }} aria-labelledby="rf-h">
              <h2 id="rf-h" className="sec-h">Needs refining first <span className="n">{refine.reduce((n, g) => n + g.toRefine.length, 0)}</span></h2>
              {refine.map((g) => (
                <div key={g.repo} className="stack" style={{ gap: 10 }}>
                  <GroupHead g={g} />
                  <RefineCards repo={g.repo} items={g.toRefine} />
                </div>
              ))}
            </section>
          ) : null}

          <section className="stack" style={{ gap: 14 }} aria-labelledby="all-h">
            <h2 id="all-h" className="sec-h">{filter ? 'Filtered issues' : 'All issues'} <span className="n">{groups.reduce((n, g) => n + (filter ? g.open.filter((i) => matches(filter, i)) : g.outside).length, 0)}</span></h2>
            {groups.map((g) => <IssueGroup key={g.repo} g={g} issues={filter ? g.open.filter((i) => matches(filter, i)) : g.outside} filtered={!!filter} />)}
          </section>
        </>
      )}
      <NewDispatchDialog open={dispatching} onOpenChange={(o) => { setDispatching(o); if (!o) setPicked([]); }} issues={run} repo={pickRepo ?? repo} />
    </div>
  );
}

function GroupHead({ g }: { g: Group }) {
  return <h3 className="grp-h"><b>{g.name}</b> <span className="mono muted">{g.repo}</span></h3>;
}

/** A repo's issue list under its header. Never shown as empty while its data is loading or stale. */
function IssueGroup({ g, issues, filtered }: { g: Group; issues: FeatureIssue[]; filtered: boolean }) {
  const pending = useSmallChangeSessions(g.repo);
  const shownPending = filtered ? [] : pending;
  if (!issues.length && !shownPending.length && !g.note) return null;
  return (
    <div className="stack" style={{ gap: 10 }}>
      <GroupHead g={g} />
      {g.note ? <p className="muted" role="status">{g.note}</p> : null}
      {issues.length || shownPending.length ? <SmallChangesTab repo={g.repo} issues={issues} pending={shownPending} /> : null}
    </div>
  );
}

/** "Where they stand": open issues by priority and status. Clicking a number filters the lists. */
function Matrix({ open, merged, filter, setFilter }: { open: FeatureIssue[]; merged: number; filter: Filter; setFilter: (f: Filter) => void }) {
  return (
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
        {filter ? <>Showing {priorityName(filter.p).toLowerCase()}, {COLS.find((c) => c.id === filter.c)!.label.toLowerCase()}. <button type="button" className="linkish" style={{ textDecoration: 'underline' }} onClick={() => setFilter(null)}>Show all</button></> : `Darker means more. Click a number to filter the list. ${merged} merged are not counted.`}
      </span>
    </section>
  );
}

/** The first 5 ready issues. With `onPick` each row has a checkbox; without it the rows are plain. */
function ReadyRows({ items, picked, onPick, lock }: { items: FeatureIssue[]; picked?: number[]; onPick?: (n: number) => void; lock?: string }) {
  const [all, setAll] = useState(false);
  if (!items.length) return <p style={{ margin: 0, opacity: 0.9 }}>Nothing is ready. Refine an issue below to make it runnable.</p>;
  return (
    <div className="stack" style={{ gap: 6 }}>
      {(all ? items : items.slice(0, 5)).map((i) => {
        const cells = (
          <>
            {onPick ? <input type="checkbox" checked={!!picked?.includes(i.n)} onChange={() => onPick(i.n)} disabled={!!lock} title={lock} aria-label={`Run #${i.n}`} /> : null}
            <span className="n">#{i.n}</span>
            <span className="t" title={i.title}>{i.title}</span>
            <span className="p">{priorityName(prio(i))}</span>
          </>
        );
        return onPick ? <label key={i.n} className="ready-r">{cells}</label> : <div key={i.n} className="ready-r np">{cells}</div>;
      })}
      {items.length > 5 ? <button type="button" className="linkish" style={{ color: 'inherit', opacity: 0.9, padding: '6px 12px 0', fontSize: 13 }} onClick={() => setAll(!all)}>{all ? 'Show fewer' : `${items.length - 5} more ready`}</button> : null}
    </div>
  );
}

/** One repo's unrefined cards, each with Refine on that repo. Locked only while that repo has a small change being created. */
function RefineCards({ repo, items }: { repo: string; items: FeatureIssue[] }) {
  const panel = usePanel();
  const starter = useStarter();
  const refining = useRefining(repo);
  const pending = useSmallChangeSessions(repo);
  const [all, setAll] = useState(false);
  const refine = (n: number) => starter.startBoard({ repo, skill: 'refine-issues', arg: String(n), via: 'headless', ...PLAN_RUN }, { nav: false });
  return (
    <>
      <div className="rgrid">
        {(all ? items : items.slice(0, 8)).map((i) => (
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
      {items.length > 8 ? <button type="button" className="linkish" style={{ alignSelf: 'flex-start', fontSize: 13, textDecoration: 'underline' }} onClick={() => setAll(!all)}>{all ? 'Show fewer' : `Show all ${items.length}`}</button> : null}
    </>
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
