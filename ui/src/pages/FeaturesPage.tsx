import { useMemo, type MouseEvent } from 'react';
import { Link } from 'react-router-dom';
import { useDelivery, useDeliveryAll, useDispatches, useInbox, needsYouCount, usePlanning, usePlanningAll } from '../api/hooks';
import type { BoardMeta, Dispatch } from '../api/types';
import { BoardStatus } from '../board/BoardStatus';
import { Button, EmptyState, useListSelection } from '../components';
import { CreatePrompt } from '../create/Create';
import { IssueBar, StageTicks } from '../features/StripParts';
import { useStepRunner } from '../features/useStepRunner';
import { useEpicDispatch } from '../dispatch/useOwner';
import { counts, needsYou, secs } from '../dispatch/vocab';
import '../features/features.css';
import '../dispatch/dispatch.css';
import { joinFeatures, snapshotsReady, type Feature } from '../lib/features';
import { money } from '../lib/format';
import { attention, nextStep, stepKey, type Attention } from '../lib/nextStep';
import { repoLink } from '../lib/repo';
import { routes } from '../lib/routes';
import { STAGES, stageIdx } from '../lib/vocab';
import { usePanel } from '../panels/PanelContext';
import { useRepo } from '../shell/useRepo';
import { useRepoFilter } from '../shell/useRepoFilter';
import { KeyScope } from '../shell/shortcuts';

const ORDER = ['review', 'draft', 'approved', 'tasks', 'building'];
const BAYS: [Attention, string][] = [['you', 'Stopped on you'], ['go', 'Waiting for your go'], ['auto', 'Running on their own']];
const featureKey = (repo: string, slug: string) => `${repo}:${slug}`;
const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();
const short = (slug: string) => slug.split('/').pop() ?? slug;
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

type RowSel = Pick<ReturnType<typeof useListSelection>, 'rowProps'> & { selected: string | null };
/** One feature in flight with its repo and who has the next move. */
type Row = { repo: string; f: Feature; kind: Attention };
type Shipped = { repo: string; f: Feature };
/** A repo with nothing to show as a strip: a note says why, else it is quiet. */
type Quiet = { repo: string; shipped: number; note: string | null };

const progress = (d: Dispatch) => { const c = counts(d); return { id: d.id, closed: c.closed, total: c.total, you: c.you }; };

/** The next move on each feature, from one read of /api/dispatches. */
function useRows() {
  const all = useDispatches().data?.dispatches ?? [];
  return (repo: string, features: Feature[]): Row[] => features.map((f) => {
    const d = f.epic ? all.find((x) => (x.state === 'running' || x.state === 'paused') && x.epic != null && same(x.epic, `${repo}#${f.epic}`)) : undefined;
    const running = d ? progress(d) : null;
    return { repo, f, kind: attention(nextStep(f, running), running) };
  });
}

/** One feature in flight: stage, issues, next step and its button on one strip. A strip stopped on you sits out of line. */
function Strip({ row, sel, showRepo }: { row: Row; sel: RowSel; showRepo: boolean }) {
  const { repo, f, kind } = row;
  const key = featureKey(repo, f.slug);
  const { run, busy, labelOf } = useStepRunner(f, repo);
  const panel = usePanel();
  const live = useEpicDispatch(repo, f.epic);
  const ns = nextStep(f, live && { id: live.d.id, closed: live.c.closed, total: live.c.total, you: live.c.you });
  const mergeable = f.issues.filter((m) => m.mergeable && m.pr);
  const i = stageIdx(f.stage);
  const target = { kind: 'feature' as const, repo, slug: f.slug };
  const open = panel.target?.kind === 'feature' && panel.target.repo === repo && panel.target.slug === f.slug;
  const you = new Set((live?.d.lanes ?? []).filter(needsYou).map((l) => l.n));
  const title = (e: MouseEvent) => {
    e.stopPropagation();
    if (e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    sel.rowProps(key).onClick();
    panel.open(target);
  };
  return (
    <article
      className={`strip ${kind}${open ? ' open' : ''}`}
      aria-label={f.title}
      {...sel.rowProps(key)}
      onClick={() => { sel.rowProps(key).onClick(); panel.open(target); }}
    >
      <span className={`hold ${STAGES[i].tone}`} aria-hidden="true" />
      <div className="strip-c strip-t">
        <Link to={repoLink(repo, routes.feature(f.slug))} onClick={title}>{f.title}</Link>
        <div className="strip-m">
          {showRepo ? <span>{short(repo)}</span> : null}
          <span>{f.epic ? `epic #${f.epic}` : 'no epic yet'}</span>
          {live ? <span>{live.d.state === 'paused' ? 'dispatch paused' : `dispatch ${secs(live.d.totals.seconds)}, ${money(live.d.totals.cost)}`}</span> : null}
        </div>
      </div>
      <div className="strip-c strip-s">
        <StageTicks at={i} />
        {STAGES[i].label}
      </div>
      <div className="strip-c strip-p">
        <IssueBar issues={f.issues} you={you} />
      </div>
      <div className="strip-c strip-n" title={ns.hint}>{ns.title}</div>
      <KeyScope level="row" active={sel.selected === key} name={f.title}>
        <div className="strip-c strip-a" onClick={(e) => e.stopPropagation()}>
          {mergeable.map((m, at) => <Button key={m.n} sm variant="primary" shortcut={at === 0 ? 'm' : undefined} onClick={() => panel.open({ kind: 'pr', repo, n: m.pr!.n })}>Merge #{m.pr!.n}</Button>)}
          {ns.primary.action.kind === 'merge' ? null : (
            <Button sm variant={kind === 'you' ? 'you' : ns.quiet || mergeable.length ? 'default' : 'primary'} shortcut={stepKey(ns.primary.action)} disabled={busy} onClick={() => run(ns.primary.action)}>{labelOf(ns.primary.action, ns.primary.label)}</Button>
          )}
        </div>
      </KeyScope>
    </article>
  );
}

/** What the page says first: who has the next move, never "nothing" while the Inbox still holds items. */
function ledeOf(rows: Row[]) {
  const n = (k: Attention) => rows.filter((r) => r.kind === k).length;
  const bits = [
    n('you') ? `${n('you')} stopped on you` : '',
    n('go') ? `${n('go')} waiting for your go` : '',
    n('auto') ? `${n('auto')} running on ${n('auto') === 1 ? 'its' : 'their'} own` : '',
  ].filter(Boolean).join(', ');
  return bits ? `${bits[0].toUpperCase()}${bits.slice(1)}.` : 'Nothing in progress.';
}

/** Filter to the repo in hand or to all of them; a quiet repo in the list below filters to that one. */
function Scope({ repo, only, setOnly }: { repo: string; only: string; setOnly: (slug: string) => void }) {
  const here = only || repo;
  return (
    <div className="scope" role="group" aria-label="Show features from">
      {here ? <button type="button" aria-pressed={!!only} onClick={() => setOnly(here)}>{short(here)}</button> : null}
      <button type="button" aria-pressed={!only} onClick={() => setOnly('')}>All repos</button>
    </div>
  );
}

function PageHead({ lede, repo, only, setOnly }: { lede: string; repo: string; only: string; setOnly: (slug: string) => void }) {
  const items = (useInbox().data?.items ?? []).filter((i) => !only || (i.repo && same(i.repo, only)));
  const inbox = needsYouCount(items);
  const { link } = useRepo();
  return (
    <div className="page-head">
      <header className="grow">
        <h1 className="display">Features</h1>
        <p className="lede">{lede}</p>
        {inbox ? <p className="inbox-note"><Link to={link(routes.inbox)}>{inbox} {inbox === 1 ? 'item waits' : 'items wait'} in Inbox</Link></p> : null}
      </header>
      <Scope repo={repo} only={only} setOnly={setOnly} />
    </div>
  );
}

const Loading = () => <div className="stack" aria-busy="true"><p className="muted" role="status">Loading features…</p><div className="skel" style={{ height: 188 }} /><div className="skel" style={{ height: 260 }} /></div>;

/** The strips by who has the next move, then one way in to create, then everything quiet. */
function Bays({ rows, shipped, quiet, showRepo, target, setOnly, onOpen }: { rows: Row[]; shipped: Shipped[]; quiet: Quiet[]; showRepo: boolean; target: string; setOnly: (slug: string) => void; onOpen: (key: string) => void }) {
  const bays = BAYS.map(([k, h]) => ({ k, h, rows: rows.filter((r) => r.kind === k) })).filter((b) => b.rows.length);
  const ordered = bays.flatMap((b) => b.rows);
  const sel = useListSelection({
    keys: ordered.map((r) => featureKey(r.repo, r.f.slug)),
    onOpen,
    panelTarget: (k) => { const r = ordered.find((x) => featureKey(x.repo, x.f.slug) === k); return r ? { kind: 'feature', repo: r.repo, slug: r.f.slug } : null; },
    reset: target,
  });
  const idle = quiet.filter((q) => !q.note);
  return (
    <>
      <div className="strips">
        {bays.map((b) => (
          <section key={b.k} className="bay" aria-labelledby={`bay-${b.k}`}>
            <h2 id={`bay-${b.k}`} className="bay-h">{b.h} <span>{b.rows.length}</span></h2>
            <div className="bay-in">{b.rows.map((r) => <Strip key={featureKey(r.repo, r.f.slug)} row={r} sel={sel} showRepo={showRepo} />)}</div>
          </section>
        ))}
        <CreatePrompt repo={target || undefined} className="strip-new" />
      </div>
      {quiet.filter((q) => q.note).map((q) => <p key={q.repo} className="fnote"><b>{short(q.repo)}</b> <span>{q.note}</span></p>)}
      {idle.length ? (
        <p className="fquiet">
          <span>Nothing in progress:</span>
          {idle.map((q) => <button key={q.repo} type="button" className="linkish" onClick={() => setOnly(q.repo)}>{short(q.repo)}{q.shipped ? ` (${q.shipped} shipped)` : ''}</button>)}
        </p>
      ) : null}
      {shipped.length ? (
        <details className="fships">
          <summary>{shipped.length} shipped</summary>
          <ul>{shipped.map(({ repo, f }) => <li key={featureKey(repo, f.slug)}><Link to={repoLink(repo, routes.feature(f.slug))}>{f.title}</Link><span>{showRepo ? short(repo) : plural(f.issues.length, 'issue')}</span></li>)}</ul>
        </details>
      ) : null}
    </>
  );
}

const splitFeatures = (features: Feature[]) => ({
  active: features.filter((f) => f.stage !== 'shipped').sort((a, b) => ORDER.indexOf(a.stage) - ORDER.indexOf(b.stage)),
  shipped: features.filter((f) => f.stage === 'shipped'),
});

const useOpenFeature = () => {
  const panel = usePanel();
  return (key: string) => { const at = key.lastIndexOf(':'); panel.open({ kind: 'feature', repo: key.slice(0, at), slug: key.slice(at + 1) }); };
};

/** Today's page for one repo (FR-3). */
function RepoBoard({ repo, setOnly }: { repo: string; setOnly: (slug: string) => void }) {
  const plan = usePlanning(repo);
  const del = useDelivery(repo);
  const rowsOf = useRows();
  const onOpen = useOpenFeature();
  const features = useMemo(() => joinFeatures(plan.data?.prds ?? [], del.data?.lanes ?? []), [plan.data, del.data]);
  const { active, shipped } = splitFeatures(features);
  const rows = rowsOf(repo, active);
  const loaded = plan.isSuccess && !del.isPending && snapshotsReady(plan.data, del.data);

  return (
    <div className="content-inner">
      <PageHead lede={loaded ? ledeOf(rows) : 'Each feature is one PRD and everything built from it.'} repo={repo} only={repo} setOnly={setOnly} />
      <BoardStatus meta={plan.data} failed={plan.isError && !!plan.data} />
      {plan.isError && !plan.data ? (
        <EmptyState icon="alert" title="Features unavailable" actions={<Button onClick={() => plan.refetch()}>Retry</Button>}>
          {plan.error.message}. It will keep retrying.
        </EmptyState>
      ) : del.isError && !del.data ? (
        <EmptyState icon="alert" title="Issues unavailable" actions={<Button onClick={() => del.refetch()}>Retry</Button>}>{del.error.message}</EmptyState>
      ) : !loaded ? <Loading /> : (
        <Bays rows={rows} shipped={shipped.map((f) => ({ repo, f }))} quiet={[]} showRepo={false} target={repo} setOnly={setOnly} onOpen={onOpen} />
      )}
    </div>
  );
}

const noteOf = (...metas: (BoardMeta | undefined)[]) => {
  const ms = metas.filter((m): m is BoardMeta => !!m);
  const error = ms.find((m) => m.error)?.error;
  return ms.some((m) => m.stale || m.error) ? `GitHub data is stale${error ? `: ${error}` : ''}` : null;
};

/** Every watched repo's in-progress features, by who has the next move (FR-4 to FR-6, FR-11). */
function AllRepos({ switcherRepo, setOnly }: { switcherRepo: string; setOnly: (slug: string) => void }) {
  const plan = usePlanningAll(true);
  const del = useDeliveryAll(true);
  const rowsOf = useRows();
  const onOpen = useOpenFeature();
  const groups = (plan.data?.repos ?? []).map((p) => {
    const d = del.data?.repos.find((x) => x.repo === p.repo);
    const { active, shipped } = splitFeatures(joinFeatures('prds' in p ? p.prds : [], d && 'lanes' in d ? d.lanes : []));
    const loading = p.fetched_at === null || d?.fetched_at === null;
    return { repo: p.repo, rows: rowsOf(p.repo, active), shipped, note: loading ? 'Still loading…' : noteOf(p, d) };
  }).sort((a, b) => a.repo.localeCompare(b.repo));
  const rows = groups.flatMap((g) => g.rows);
  const shipped = groups.flatMap((g) => g.shipped.map((f) => ({ repo: g.repo, f })));
  const quiet = groups.filter((g) => !g.rows.length || g.note).map((g) => ({ repo: g.repo, shipped: g.shipped.length, note: g.note }));
  const ready = !!plan.data && !!del.data;
  const unsettled = groups.some((g) => g.note);
  const lede = !ready ? 'Each feature is one PRD and everything built from it.'
    : !groups.length ? 'No repo opened recently.'
    : !rows.length && unsettled ? 'Each feature is one PRD and everything built from it.'
    : ledeOf(rows);

  return (
    <div className="content-inner">
      <PageHead lede={lede} repo={switcherRepo} only="" setOnly={setOnly} />
      <BoardStatus />
      {plan.isError && !plan.data ? (
        <EmptyState icon="alert" title="Features unavailable" actions={<Button onClick={() => plan.refetch()}>Retry</Button>}>
          {plan.error.message}. It will keep retrying.
        </EmptyState>
      ) : del.isError && !del.data ? (
        <EmptyState icon="alert" title="Issues unavailable" actions={<Button onClick={() => del.refetch()}>Retry</Button>}>{del.error.message}</EmptyState>
      ) : !ready ? <Loading /> : !groups.length ? (
        <p className="muted">No repo opened recently. Pick one in the top bar.</p>
      ) : (
        <Bays rows={rows} shipped={shipped} quiet={quiet} showRepo target={switcherRepo} setOnly={setOnly} onOpen={onOpen} />
      )}
    </div>
  );
}

export function FeaturesPage() {
  const { repo } = useRepo();
  const { only, setOnly } = useRepoFilter();
  return only ? <RepoBoard repo={only} setOnly={setOnly} /> : <AllRepos switcherRepo={repo} setOnly={setOnly} />;
}
