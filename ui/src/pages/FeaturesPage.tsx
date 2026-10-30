import { useMemo, type CSSProperties } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useDelivery, useDeliveryAll, usePlanning, usePlanningAll, useRepos } from '../api/hooks';
import type { BoardMeta, Dispatch } from '../api/types';
import { BoardStatus } from '../board/BoardStatus';
import { Button, EmptyState, useListSelection } from '../components';
import { CaptureBar } from '../features/CaptureBar';
import { lineColor, SubwayMap } from '../features/SubwayMap';
import { useStepRunner } from '../features/useStepRunner';
import { useEpicDispatch } from '../dispatch/useOwner';
import { counts, needsYou, secs } from '../dispatch/vocab';
import { useDispatches } from '../api/hooks';
import '../features/features.css';
import '../dispatch/dispatch.css';
import { countBy, joinFeatures, snapshotsReady, type Feature } from '../lib/features';
import { money } from '../lib/format';
import { nextStep, stepKey } from '../lib/nextStep';
import { repoLink } from '../lib/repo';
import { routes } from '../lib/routes';
import { STAGES, stageIdx } from '../lib/vocab';
import { usePanel } from '../panels/PanelContext';
import { RepoSelect } from '../shell/RepoSelect';
import { useRepo } from '../shell/useRepo';
import { useRepoFilter } from '../shell/useRepoFilter';
import { KeyScope } from '../shell/shortcuts';

const ORDER = ['review', 'draft', 'approved', 'tasks', 'building'];
const featureKey = (repo: string, slug: string) => `${repo}:${slug}`;
const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

/** Live dispatch of each epic, so the pipeline and the cards share one read of /api/dispatches. */
function useLiveByEpic() {
  const all = useDispatches().data?.dispatches ?? [];
  return (repo: string, epic: number | null): Dispatch | undefined =>
    epic ? all.find((d) => (d.state === 'running' || d.state === 'paused') && d.epic != null && same(d.epic, `${repo}#${epic}`)) : undefined;
}

type RowSel = Pick<ReturnType<typeof useListSelection>, 'rowProps'> & { selected: string | null };

/** One feature in flight: its issues as squares, the merged count, and the next step with its button. */
/** `color` is the feature's line on the map above, so a card and its line match. */
function Card({ f, repo, sel, color }: { f: Feature; repo: string; sel: RowSel; color: string }) {
  const key = featureKey(repo, f.slug);
  const navigate = useNavigate();
  const { run, busy } = useStepRunner(f, repo);
  const panel = usePanel();
  const live = useEpicDispatch(repo, f.epic);
  const ns = nextStep(f, live && { id: live.d.id, closed: live.c.closed, total: live.c.total, you: live.c.you });
  const ready = f.issues.filter((i) => i.mergeable && i.pr);
  const youLanes = new Set((live?.d.lanes ?? []).filter(needsYou).map((l) => l.n));
  const you = !!live?.c.you;
  const merged = countBy(f.issues).merged ?? 0;
  const i = stageIdx(f.stage);
  const href = repoLink(repo, routes.feature(f.slug));
  const size = f.issues.length > 24 ? 10 : 22;
  return (
    <article
      className={`fcard${you ? ' you' : ''}`}
      style={{ '--st': color } as CSSProperties}
      aria-label={f.title}
      {...sel.rowProps(key)}
      onClick={() => { sel.rowProps(key).onClick(); navigate(href); }}
    >
      <div className="fcard-b">
        <div className="stack" style={{ gap: 6 }}>
          <Link className="fcard-t" to={href} onClick={(e) => e.stopPropagation()}>{f.title}</Link>
          <div className="fcard-m">
            <span>{STAGES[i].label}</span>
            <span>{f.epic ? `epic #${f.epic}` : 'no epic yet'}</span>
            {live ? <span>{live.d.state === 'paused' ? 'dispatch paused' : `dispatch ${secs(live.d.totals.seconds)} · ${money(live.d.totals.cost)}`}</span> : null}
          </div>
        </div>
        {f.issues.length ? (
          <div className="fcard-p">
            <div className="cells" style={{ '--cs': `${size}px` } as CSSProperties} role="img" aria-label={`${merged} of ${f.issues.length} issues merged`}>
              {f.issues.map((x) => <i key={x.n} className={youLanes.has(x.n) ? 'you' : x.status} title={`#${x.n} ${x.title}`} />)}
            </div>
            <div className="big"><b>{merged}<small>/{f.issues.length}</small></b><span>merged</span></div>
          </div>
        ) : null}
        <KeyScope level="row" active={sel.selected === key} name={f.title}>
          <div className="fnext-b" onClick={(e) => e.stopPropagation()}>
            <p><b>{ns.title}.</b> {ns.hint}</p>
            <div className="row wrap">
              {ready.map((r, at) => <Button key={r.n} sm variant="primary" shortcut={at === 0 ? 'm' : undefined} onClick={() => panel.open({ kind: 'pr', repo, n: r.pr!.n })}>Merge #{r.pr!.n}</Button>)}
              {ns.primary.action.kind === 'merge' ? null : (
                <Button sm variant={you ? 'you' : ns.quiet ? 'default' : 'primary'} shortcut={stepKey(ns.primary.action)} disabled={busy} onClick={() => run(ns.primary.action)}>{ns.primary.label}</Button>
              )}
            </div>
          </div>
        </KeyScope>
      </div>
    </article>
  );
}

type Group = { repo: string; name: string; active: Feature[]; shipped: number; stuck: number; loading: boolean; note: string | null };

const splitFeatures = (features: Feature[]) => ({
  active: features.filter((f) => f.stage !== 'shipped').sort((a, b) => ORDER.indexOf(a.stage) - ORDER.indexOf(b.stage)),
  shipped: features.filter((f) => f.stage === 'shipped'),
});

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** FR-4: stopped-on-you first, then more in progress, then by name; a repo with nothing to show goes last as one line. */
const idle = (g: Group) => !g.active.length && !g.loading && !g.note;
const byGroup = (a: Group, b: Group) =>
  Number(idle(a)) - Number(idle(b)) || Number(b.stuck > 0) - Number(a.stuck > 0) || b.active.length - a.active.length || a.name.localeCompare(b.name);

function PageHead({ lede, only, setOnly }: { lede: string; only: string; setOnly: (slug: string) => void }) {
  const repos = useRepos().data?.repos ?? [];
  return (
    <div className="page-head">
      <header className="grow">
        <h1 className="display">Features</h1>
        <p className="lede">{lede}</p>
      </header>
      <RepoSelect repos={repos} value={only} onChange={setOnly} label="Repo filter" width={180} extrasBefore={[{ value: '', label: 'All repos' }]} />
    </div>
  );
}

const Legend = () => (
  <div className="legend" aria-hidden="true">
    <span><i style={{ background: 'var(--ship)' }} />Merged</span>
    <span><i style={{ background: 'var(--review)' }} />In review</span>
    <span><i style={{ background: 'var(--build)' }} />Building</span>
    <span><i style={{ background: 'var(--plan)' }} />Ready</span>
    <span><i style={{ border: '1.5px dashed var(--faint)' }} />Needs refining</span>
    <span><i style={{ background: 'var(--you)' }} />Needs you</span>
  </div>
);

/** Today's page for one repo (FR-3). */
function RepoBoard({ repo, setOnly }: { repo: string; setOnly: (slug: string) => void }) {
  const navigate = useNavigate();
  const plan = usePlanning(repo);
  const del = useDelivery(repo);
  const liveOf = useLiveByEpic();
  const features = useMemo(() => joinFeatures(plan.data?.prds ?? [], del.data?.lanes ?? []), [plan.data, del.data]);
  const { active, shipped } = splitFeatures(features);
  const stuck = active.filter((f) => { const d = liveOf(repo, f.epic); return !!d && counts(d).you > 0; });
  const sel = useListSelection({
    keys: active.map((f) => featureKey(repo, f.slug)),
    onOpen: (k) => navigate(repoLink(repo, routes.feature(k.slice(repo.length + 1)))),
    reset: repo,
  });
  const loaded = plan.isSuccess && !del.isPending && snapshotsReady(plan.data, del.data);
  const lede = !loaded ? 'Each feature is one PRD and everything built from it.'
    : stuck.length ? `${stuck.length === active.length ? (active.length === 1 ? 'The feature' : `All ${active.length} features`) : `${stuck.length} of ${active.length} features`} in progress ${stuck.length === 1 ? 'is' : 'are'} stopped on you.`
    : active.length ? `${active.length} in progress, ${shipped.length} shipped. Nothing is waiting on you.`
    : 'Nothing in progress. Describe what to build above.';

  return (
    <div className="content-inner">
      <CaptureBar repo={repo} />
      <PageHead lede={lede} only={repo} setOnly={setOnly} />
      <BoardStatus meta={plan.data} failed={plan.isError && !!plan.data} />
      {plan.isError && !plan.data ? (
        <EmptyState icon="alert" title="Features unavailable" actions={<Button onClick={() => plan.refetch()}>Retry</Button>}>
          {plan.error.message}. It will keep retrying.
        </EmptyState>
      ) : del.isError && !del.data ? (
        <EmptyState icon="alert" title="Issues unavailable" actions={<Button onClick={() => del.refetch()}>Retry</Button>}>{del.error.message}</EmptyState>
      ) : !loaded ? (
        <div className="stack" aria-busy="true"><p className="muted" role="status">Loading features…</p><div className="skel" style={{ height: 188 }} /><div className="skel" style={{ height: 260 }} /></div>
      ) : (
        <>
          {/* active lines first (their colours match the cards below), then the last few to ship */}
          {active.length || shipped.length ? <SubwayMap features={[...active, ...shipped.slice(0, 3)]} stuck={stuck} /> : null}

          <section className="stack" style={{ gap: 14 }} aria-labelledby="flight-h">
            <h2 id="flight-h" className="sec-h">In progress <span className="n">{active.length}</span></h2>
            {active.length ? (
              <>
                <div className="fgrid">{active.map((f, k) => <Card key={f.slug} f={f} repo={repo} sel={sel} color={lineColor(k)} />)}</div>
                <Legend />
              </>
            ) : <p className="muted" style={{ margin: 0 }}>Nothing in progress.</p>}
          </section>

          {shipped.length ? (
            <section className="stack" style={{ gap: 14 }} aria-labelledby="ship-h">
              <h2 id="ship-h" className="sec-h">Shipped <span className="n">{shipped.length}</span></h2>
              <div className="shipped">
                {shipped.map((f) => <Link key={f.slug} to={repoLink(repo, routes.feature(f.slug))}>{f.title}<span>{f.issues.length}</span></Link>)}
              </div>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}

const noteOf = (...metas: (BoardMeta | undefined)[]) => {
  const ms = metas.filter((m): m is BoardMeta => !!m);
  const error = ms.find((m) => m.error)?.error;
  return ms.some((m) => m.stale || m.error) ? `GitHub data is stale${error ? `: ${error}` : ''}` : null;
};

/** Every watched repo's in-progress features, one group per repo (FR-4 to FR-6, FR-11). */
function AllRepos({ switcherRepo, setOnly }: { switcherRepo: string; setOnly: (slug: string) => void }) {
  const navigate = useNavigate();
  const plan = usePlanningAll(true);
  const del = useDeliveryAll(true);
  const names = new Map((useRepos().data?.repos ?? []).map((r) => [r.slug, r.name]));
  const liveOf = useLiveByEpic();
  const groups: Group[] = (plan.data?.repos ?? []).map((p) => {
    const d = del.data?.repos.find((x) => x.repo === p.repo);
    const { active, shipped } = splitFeatures(joinFeatures('prds' in p ? p.prds : [], d && 'lanes' in d ? d.lanes : []));
    return {
      repo: p.repo, name: names.get(p.repo) || p.repo, active, shipped: shipped.length,
      stuck: active.filter((f) => { const l = liveOf(p.repo, f.epic); return !!l && counts(l).you > 0; }).length,
      loading: p.fetched_at === null || d?.fetched_at === null,
      note: noteOf(p, d),
    };
  }).sort(byGroup);
  const cards = groups.flatMap((g) => g.active.map((f) => ({ repo: g.repo, slug: f.slug, key: featureKey(g.repo, f.slug) })));
  const sel = useListSelection({
    keys: cards.map((c) => c.key),
    onOpen: (k) => { const c = cards.find((x) => x.key === k); if (c) navigate(repoLink(c.repo, routes.feature(c.slug))); },
    reset: 'all',
  });
  const total = groups.reduce((n, g) => n + g.active.length, 0);
  const stuck = groups.reduce((n, g) => n + g.stuck, 0);
  const across = groups.filter((g) => g.active.length).length;
  const ready = !!plan.data && !!del.data;
  const lede = !ready ? 'Each feature is one PRD and everything built from it.'
    : !groups.length ? 'No repo opened recently.'
    : !total ? (groups.some((g) => g.loading || g.note) ? 'Each feature is one PRD and everything built from it.' : 'Nothing in progress. Describe what to build above.')
    : `${total} in progress across ${plural(across, 'repo')}${stuck ? `; ${stuck} ${stuck === 1 ? 'is' : 'are'} stopped on you.` : '. Nothing is waiting on you.'}`;

  return (
    <div className="content-inner">
      <CaptureBar repo={switcherRepo} pickRepo />
      <PageHead lede={lede} only="" setOnly={setOnly} />
      <BoardStatus />
      {plan.isError && !plan.data ? (
        <EmptyState icon="alert" title="Features unavailable" actions={<Button onClick={() => plan.refetch()}>Retry</Button>}>
          {plan.error.message}. It will keep retrying.
        </EmptyState>
      ) : del.isError && !del.data ? (
        <EmptyState icon="alert" title="Issues unavailable" actions={<Button onClick={() => del.refetch()}>Retry</Button>}>{del.error.message}</EmptyState>
      ) : !ready ? (
        <div className="stack" aria-busy="true"><p className="muted" role="status">Loading features…</p><div className="skel" style={{ height: 188 }} /><div className="skel" style={{ height: 260 }} /></div>
      ) : !groups.length ? (
        <p className="muted">No repo opened recently. Pick one in the filter.</p>
      ) : groups.map((g) => idle(g) ? (
        <p key={g.repo} className="fgroup-idle"><b>{g.name}</b> <span className="slug">{g.repo}</span> · nothing in progress · {g.shipped} shipped</p>
      ) : (
        <section key={g.repo} className="stack" style={{ gap: 14 }} aria-labelledby={`g-${g.repo}`}>
          <h2 id={`g-${g.repo}`} className="sec-h fgroup-h">
            {g.name}
            {g.name !== g.repo ? <span className="slug">{g.repo}</span> : null}
            <span className="n">{g.active.length} in progress · {g.shipped} shipped</span>
          </h2>
          {g.loading ? <p className="muted" role="status" style={{ margin: 0 }}>Still loading…</p> : g.note ? <p className="muted" style={{ margin: 0 }}>{g.note}</p> : null}
          {g.active.length ? <div className="fgrid">{g.active.map((f, k) => <Card key={f.slug} f={f} repo={g.repo} sel={sel} color={lineColor(k)} />)}</div> : null}
        </section>
      ))}
      {total ? <Legend /> : null}
    </div>
  );
}

export function FeaturesPage() {
  const { repo } = useRepo();
  const { only, setOnly } = useRepoFilter();
  return only ? <RepoBoard repo={only} setOnly={setOnly} /> : <AllRepos switcherRepo={repo} setOnly={setOnly} />;
}
