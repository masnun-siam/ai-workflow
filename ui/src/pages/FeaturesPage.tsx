import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useDelivery, usePlanning } from '../api/hooks';
import { BoardStatus } from '../board/BoardStatus';
import { Button, Chip, EmptyState, Icon, TabPanel, Tabs, Track } from '../components';
import { useStepRunner } from '../features/useStepRunner';
import { useEpicDispatch } from '../dispatch/useOwner';
import { IdeaBox } from '../features/IdeaBox';
import '../features/features.css';
import type { DeliveryLane } from '../api/types';
import '../dispatch/dispatch.css';
import { joinFeatures, snapshotsReady, type Feature } from '../lib/features';
import { agoIso } from '../lib/format';
import { nextStep } from '../lib/nextStep';
import { routes } from '../lib/routes';
import { STAGES, stageIdx } from '../lib/vocab';
import { usePanel } from '../panels/PanelContext';
import { useRepo } from '../shell/useRepo';
import { useStart } from '../start/StartContext';

const ORDER = ['review', 'draft', 'approved', 'tasks', 'building'];

const updated = (m: number) => {
  const a = agoIso(new Date(m * 1000).toISOString());
  return a === 'now' ? 'just now' : `${a} ago`;
};

function Row({ f, repo }: { f: Feature; repo: string }) {
  const navigate = useNavigate();
  const { link } = useRepo();
  const { run, busy } = useStepRunner(f, repo);
  const panel = usePanel();
  const live = useEpicDispatch(repo, f.epic);
  const ns = nextStep(f, live && { id: live.d.id, closed: live.c.closed, total: live.c.total, you: live.c.you });
  const ready = f.issues.filter((i) => i.mergeable && i.pr);
  const st = STAGES[stageIdx(f.stage)];
  const href = link(routes.feature(f.slug));
  return (
    <div className="frow" onClick={() => navigate(href)}>
      <div style={{ minWidth: 0 }}>
        <div className="ftitle"><Link to={href} onClick={(e) => e.stopPropagation()}>{f.title}</Link></div>
        <div className="fmeta">
          <span>{f.epic ? `Epic #${f.epic}` : 'No epic yet'}</span>
          {live ? <span className={live.c.you ? 'dsp-c t-you' : ''}>{live.c.you ? `Dispatch needs you on ${live.c.you}` : `Dispatch running, ${live.c.closed} of ${live.c.total} done`}</span> : null}
          {f.prd.mtime ? <span>Updated {updated(f.prd.mtime)}</span> : null}
        </div>
      </div>
      <div><Chip tone={st.tone}>{st.label}</Chip></div>
      <Track feature={f} />
      <div className="fnext" onClick={(e) => e.stopPropagation()}>
        {ready.map((i) => <Button key={i.n} sm variant="primary" onClick={() => panel.open({ kind: 'pr', repo, n: i.pr!.n })}>Merge #{i.pr!.n}</Button>)}
        {ns.primary.action.kind === 'merge' ? null : <Button sm variant={ns.quiet ? 'default' : 'primary'} disabled={busy} onClick={() => run(ns.primary.action)}>{ns.primary.label}</Button>}
      </div>
    </div>
  );
}

/** The last row: open issues that belong to no feature, when there are any. */
function OtherRow({ features, lanes }: { features: Feature[]; lanes: DeliveryLane[] }) {
  const { link } = useRepo();
  const mine = new Set(features.flatMap((f) => f.issues.map((i) => i.n)));
  const n = lanes.flatMap((l) => l.cards).filter((c) => !mine.has(c.n)).length;
  if (!n) return null;
  return (
    <Link to={link(routes.otherIssues)} className="frow other" style={{ textDecoration: 'none', color: 'inherit' }}>
      <div><div className="ftitle">Other issues</div><div className="fmeta"><span>Open issues that are not part of a feature</span></div></div>
      <div><Chip>{n} open</Chip></div>
    </Link>
  );
}

export function FeaturesPage() {
  const { repo, current } = useRepo();
  const start = useStart();
  const plan = usePlanning(repo);
  const del = useDelivery(repo);
  const [tab, setTab] = useState('active');
  const features = useMemo(() => joinFeatures(plan.data?.prds ?? [], del.data?.lanes ?? []), [plan.data, del.data]);
  const active = features.filter((f) => f.stage !== 'shipped').sort((a, b) => ORDER.indexOf(a.stage) - ORDER.indexOf(b.stage));
  const shipped = features.filter((f) => f.stage === 'shipped');
  const list = tab === 'active' ? active : shipped;
  const loaded = plan.isSuccess && !del.isPending && snapshotsReady(plan.data, del.data);

  return (
    <div className="content-inner">
      <div className="page-head">
        <div className="grow"><h1>Features</h1><p className="sub">Each feature is one PRD and everything built from it.</p></div>
        <Button variant="primary" onClick={() => start.open({ cmd: 'create-prd', repo })}><Icon n="plus" />New feature</Button>
      </div>
      <BoardStatus meta={plan.data} failed={plan.isError && !!plan.data} />
      {plan.isError && !plan.data ? (
        <EmptyState icon="alert" title="Features unavailable" actions={<Button onClick={() => plan.refetch()}>Retry</Button>}>
          {plan.error.message}. It will keep retrying.
        </EmptyState>
      ) : !loaded ? (
        <div className="stack" aria-busy="true"><p className="muted" role="status">Loading features…</p>{[0, 1, 2].map((j) => <div key={j} className="skel" style={{ height: 56 }} />)}</div>
      ) : features.length === 0 ? (
        <>
          <IdeaBox repo={repo} name={current?.name ?? repo} />
          <div className="list"><OtherRow features={features} lanes={del.data?.lanes ?? []} /></div>
        </>
      ) : (
        <Tabs
          value={tab}
          onValueChange={setTab}
          label="Features"
          tabs={[{ value: 'active', label: 'In progress', count: active.length }, { value: 'shipped', label: 'Shipped', count: shipped.length }]}
        >
          <TabPanel value={tab}>
            <div className="list">{list.map((f) => <Row key={f.slug} f={f} repo={repo} />)}</div>
            {!list.length ? <p className="muted">Nothing here yet.</p> : null}
            {tab === 'active' ? <OtherRow features={features} lanes={del.data?.lanes ?? []} /> : null}
          </TabPanel>
        </Tabs>
      )}
    </div>
  );
}
