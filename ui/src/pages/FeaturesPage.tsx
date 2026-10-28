import { useMemo, type CSSProperties } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useDelivery, usePlanning } from '../api/hooks';
import type { Dispatch } from '../api/types';
import { BoardStatus } from '../board/BoardStatus';
import { Button, EmptyState, useListSelection } from '../components';
import { CaptureBar } from '../features/CaptureBar';
import { useStepRunner } from '../features/useStepRunner';
import { useEpicDispatch } from '../dispatch/useOwner';
import { counts, needsYou, secs } from '../dispatch/vocab';
import { useDispatches } from '../api/hooks';
import '../features/features.css';
import '../dispatch/dispatch.css';
import { countBy, joinFeatures, snapshotsReady, type Feature } from '../lib/features';
import { money } from '../lib/format';
import { nextStep, stepKey } from '../lib/nextStep';
import { routes } from '../lib/routes';
import { STAGES, stageIdx } from '../lib/vocab';
import { usePanel } from '../panels/PanelContext';
import { useRepo } from '../shell/useRepo';
import { KeyScope } from '../shell/shortcuts';

const ORDER = ['review', 'draft', 'approved', 'tasks', 'building'];
const st = (i: number) => ({ '--st': `var(--st${i})` }) as CSSProperties;
const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

/** Live dispatch of each epic, so the pipeline and the cards share one read of /api/dispatches. */
function useLiveByEpic(repo: string) {
  const all = useDispatches().data?.dispatches ?? [];
  return (epic: number | null): Dispatch | undefined =>
    epic ? all.find((d) => (d.state === 'running' || d.state === 'paused') && d.epic != null && same(d.epic, `${repo}#${epic}`)) : undefined;
}

type RowSel = Pick<ReturnType<typeof useListSelection>, 'rowProps'> & { selected: string | null };

/** One feature in flight: its issues as squares, the merged count, and the next step with its button. */
function Card({ f, repo, sel }: { f: Feature; repo: string; sel: RowSel }) {
  const navigate = useNavigate();
  const { link } = useRepo();
  const { run, busy } = useStepRunner(f, repo);
  const panel = usePanel();
  const live = useEpicDispatch(repo, f.epic);
  const ns = nextStep(f, live && { id: live.d.id, closed: live.c.closed, total: live.c.total, you: live.c.you });
  const ready = f.issues.filter((i) => i.mergeable && i.pr);
  const youLanes = new Set((live?.d.lanes ?? []).filter(needsYou).map((l) => l.n));
  const you = !!live?.c.you;
  const merged = countBy(f.issues).merged ?? 0;
  const i = stageIdx(f.stage);
  const href = link(routes.feature(f.slug));
  const size = f.issues.length > 24 ? 10 : 22;
  return (
    <article
      className={`fcard${you ? ' you' : ''}`}
      style={st(i)}
      aria-label={f.title}
      {...sel.rowProps(f.slug)}
      onClick={() => { sel.rowProps(f.slug).onClick(); navigate(href); }}
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
        <KeyScope level="row" active={sel.selected === f.slug} name={f.title}>
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

export function FeaturesPage() {
  const { repo, link } = useRepo();
  const navigate = useNavigate();
  const plan = usePlanning(repo);
  const del = useDelivery(repo);
  const liveOf = useLiveByEpic(repo);
  const features = useMemo(() => joinFeatures(plan.data?.prds ?? [], del.data?.lanes ?? []), [plan.data, del.data]);
  const active = features.filter((f) => f.stage !== 'shipped').sort((a, b) => ORDER.indexOf(a.stage) - ORDER.indexOf(b.stage));
  const shipped = features.filter((f) => f.stage === 'shipped');
  const stuck = active.filter((f) => { const d = liveOf(f.epic); return !!d && counts(d).you > 0; });
  const sel = useListSelection({ keys: active.map((f) => f.slug), onOpen: (slug) => navigate(link(routes.feature(slug))), reset: repo });
  const loaded = plan.isSuccess && !del.isPending && snapshotsReady(plan.data, del.data);
  const lede = !loaded ? 'Each feature is one PRD and everything built from it.'
    : stuck.length ? `${stuck.length === active.length ? (active.length === 1 ? 'The feature' : `All ${active.length} features`) : `${stuck.length} of ${active.length} features`} in progress ${stuck.length === 1 ? 'is' : 'are'} stopped on you.`
    : active.length ? `${active.length} in progress, ${shipped.length} shipped. Nothing is waiting on you.`
    : 'Nothing in progress. Describe what to build above.';

  return (
    <div className="content-inner">
      <CaptureBar repo={repo} />
      <header>
        <h1 className="display">Features</h1>
        <p className="lede">{lede}</p>
      </header>
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
          <section className="pipe" aria-label="Pipeline">
            {STAGES.map((s, i) => {
              const here = features.filter((f) => f.stage === s.id);
              const shown = s.id === 'shipped' ? here.slice(0, 2) : here;
              return (
                <div key={s.id} className={`pipe-t${here.length ? '' : ' empty-t'}`} style={st(i)}>
                  <div className="pipe-h"><b>{s.label}</b><span>{here.length}</span></div>
                  <div className="stack" style={{ gap: 6 }}>
                    {shown.map((f) => (
                      <Link key={f.slug} to={link(routes.feature(f.slug))} className={`pipe-i${stuck.includes(f) ? ' you' : ''}`}><i /><span>{f.title}</span></Link>
                    ))}
                    {here.length > shown.length ? <span className="muted" style={{ fontSize: 12.5, padding: '0 10px' }}>+{here.length - shown.length} more</span> : null}
                  </div>
                </div>
              );
            })}
          </section>

          <section className="stack" style={{ gap: 14 }} aria-labelledby="flight-h">
            <h2 id="flight-h" className="sec-h">In progress <span className="n">{active.length}</span></h2>
            {active.length ? (
              <>
                <div className="fgrid">{active.map((f) => <Card key={f.slug} f={f} repo={repo} sel={sel} />)}</div>
                <div className="legend" aria-hidden="true">
                  <span><i style={{ background: 'var(--ship)' }} />Merged</span>
                  <span><i style={{ background: 'var(--review)' }} />In review</span>
                  <span><i style={{ background: 'var(--build)' }} />Building</span>
                  <span><i style={{ background: 'var(--plan)' }} />Ready</span>
                  <span><i style={{ border: '1.5px dashed var(--faint)' }} />Needs refining</span>
                  <span><i style={{ background: 'var(--you)' }} />Needs you</span>
                </div>
              </>
            ) : <p className="muted" style={{ margin: 0 }}>Nothing in progress.</p>}
          </section>

          {shipped.length ? (
            <section className="stack" style={{ gap: 14 }} aria-labelledby="ship-h">
              <h2 id="ship-h" className="sec-h">Shipped <span className="n">{shipped.length}</span></h2>
              <div className="shipped">
                {shipped.map((f) => <Link key={f.slug} to={link(routes.feature(f.slug))}>{f.title}<span>{f.issues.length}</span></Link>)}
              </div>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
