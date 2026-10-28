import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import type { BoardMeta } from '../api/types';
import { useDelivery, usePlanning, useSessions } from '../api/hooks';
import { SessionTable } from '../activity/SessionTable';
import { BoardStatus } from '../board/BoardStatus';
import { Button, EmptyState, Icon, LinkButton, MoreMenu, TabPanel, Tabs } from '../components';
import { IssuesTab } from '../features/IssuesTab';
import { NextStepBox } from '../features/NextStepBox';
import { PrdTab } from '../features/PrdTab';
import { ReviewTab } from '../features/ReviewTab';
import { BuildMap, DispatchPanel, StageStrip } from '../features/BuildMap';
import { useStepRunner } from '../features/useStepRunner';
import { NewDispatchDialog } from '../dispatch/NewDispatchDialog';
import { useEpicDispatch } from '../dispatch/useOwner';
import '../features/features.css';
import { joinFeatures, snapshotsReady, type Feature } from '../lib/features';
import { sessionSlug } from '../lib/format';
import { routes } from '../lib/routes';
import { stageIdx } from '../lib/vocab';
import { useRepo } from '../shell/useRepo';

const TABS = ['issues', 'prd', 'review', 'sessions'];

function Body({ f, repo, tab, meta }: { f: Feature; repo: string; tab?: string; meta?: BoardMeta }) {
  const navigate = useNavigate();
  const { link } = useRepo();
  const sessions = useSessions().data?.sessions ?? [];
  const nums = new Set(f.issues.map((i) => i.n));
  const mine = useMemo(
    () =>
      sessions.filter((s) => {
        const slug = sessionSlug(s);
        if (slug && slug !== repo) return false;
        const l = s.link;
        const issue = l && typeof l === 'object' ? l.issue : null;
        return (issue != null && (nums.has(issue) || issue === f.epic)) || s.command.includes(f.prd.path) || (!!f.panel && s.peer_review?.panel === f.panel.id);
      }),
    [sessions, f, repo], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const { run } = useStepRunner(f, repo);
  const i = stageIdx(f.stage);
  const cur = TABS.includes(tab ?? '') ? tab! : f.stage === 'review' ? 'review' : i >= 3 ? 'issues' : 'prd';
  const go = (t: string) => navigate(link(routes.feature(f.slug, t)), { replace: true });
  const [dispatching, setDispatching] = useState(false);
  const live = useEpicDispatch(repo, f.epic);
  const liveFull = live?.d;

  return (
    <div className="content-inner">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={link(routes.features)} style={{ textDecoration: 'none' }}>Features</Link>
        <Icon n="right" s={13} />
        <span>{f.title}</span>
      </nav>
      <header className="fhead">
        <h1>{f.title}</h1>
        <div className="row wrap" style={{ gap: 10 }}>
          <span className="mono muted" style={{ fontSize: 12.5 }}>{f.epic ? `epic #${f.epic} · ` : ''}{f.prd.path}</span>
          <span className="grow" />
        {live ? (
          <LinkButton to={link(routes.dispatch(live.d.id))}>
            <Icon n="bolt" />{live.c.you ? `Dispatch needs you (${live.c.you})` : `Dispatch: ${live.c.closed} of ${live.c.total} done`}
          </LinkButton>
        ) : f.epic && f.issues.length ? (
          <Button variant="primary" onClick={() => setDispatching(true)} title="Build the epic's issues side by side">
            <Icon n="bolt" />Run epic
          </Button>
        ) : null}
        <MoreMenu
          label="More"
          sm={false}
          items={[
            { label: 'Open PRD on GitHub', icon: 'ext', onSelect: () => window.open(`https://github.com/${repo}/blob/HEAD/${f.prd.path}`, '_blank', 'noopener') },
            { label: 'Add a task', icon: 'plus', onSelect: () => { go('issues'); setTimeout(() => document.getElementById('add-task')?.focus(), 50); }, disabled: !f.epic },
            ...(f.epic ? [{ label: 'Close epic and its issues', icon: 'x' as const, danger: true, onSelect: () => void run({ kind: 'closeEpic' }) }] : []),
          ]}
        />
        </div>
      </header>
      <BoardStatus meta={meta} />
      <StageStrip f={f} />
      <NextStepBox f={f} repo={repo} />
      <BuildMap f={f} repo={repo} dispatch={liveFull} />
      {live ? <div className="fpanels"><DispatchPanel id={live.d.id} /></div> : null}
      <Tabs
        value={cur}
        onValueChange={go}
        label="Feature"
        pageKeys
        tabs={[
          { value: 'issues', label: 'Issues', count: f.issues.length },
          { value: 'prd', label: 'PRD' },
          { value: 'review', label: 'Peer review' },
          { value: 'sessions', label: 'Sessions', count: mine.length },
        ]}
      >
        <TabPanel value="issues"><IssuesTab f={f} repo={repo} /></TabPanel>
        <TabPanel value="prd">{cur === 'prd' ? <PrdTab f={f} repo={repo} /> : null}</TabPanel>
        <TabPanel value="review"><ReviewTab f={f} repo={repo} /></TabPanel>
        <TabPanel value="sessions"><SessionTable rows={mine} /></TabPanel>
      </Tabs>
      {f.epic ? <NewDispatchDialog open={dispatching} onOpenChange={setDispatching} epic={`${repo}#${f.epic}`} /> : null}
    </div>
  );
}

export function FeaturePage() {
  const { slug = '', tab } = useParams();
  const { repo, link } = useRepo();
  const plan = usePlanning(repo);
  const del = useDelivery(repo);
  const f = useMemo(() => joinFeatures(plan.data?.prds ?? [], del.data?.lanes ?? []).find((x) => x.slug === slug), [plan.data, del.data, slug]);

  if (plan.isError && !plan.data)
    return <div className="content-inner"><EmptyState icon="alert" title="Could not load this feature" actions={<Button onClick={() => plan.refetch()}>Retry</Button>}>{plan.error.message}</EmptyState></div>;
  if (!plan.isSuccess || del.isPending || !snapshotsReady(plan.data, del.data))
    return (
      <div className="content-inner" aria-busy="true">
        <p className="muted" role="status">Loading…</p>
        <BoardStatus meta={plan.data} />
        <div className="stack">{[0, 1].map((j) => <div key={j} className="skel" style={{ height: 70 }} />)}</div>
      </div>
    );
  if (!f)
    return (
      <div className="content-inner">
        <EmptyState icon="file" title="Feature not found" actions={<Link className="btn" to={link(routes.features)}>Back to features</Link>}>
          No PRD called “{slug}” in {repo}. It may have been renamed, or it belongs to another repo.
        </EmptyState>
      </div>
    );
  return (
    <Body f={f} repo={repo} tab={tab} meta={plan.data} />
  );
}
