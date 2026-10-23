// Open issues that belong to no feature of this repo: no epic, or an epic with no PRD here.
import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useDelivery, usePlanning } from '../api/hooks';
import { BoardStatus } from '../board/BoardStatus';
import { Button, EmptyState, Icon } from '../components';
import { IssueTable } from '../features/IssuesTab';
import '../features/features.css';
import { joinFeatures, snapshotsReady } from '../lib/features';
import { routes } from '../lib/routes';
import { issueStatus } from '../lib/vocab';
import { useRepo } from '../shell/useRepo';

export function OtherIssuesPage() {
  const { repo, link } = useRepo();
  const plan = usePlanning(repo);
  const del = useDelivery(repo);
  const issues = useMemo(() => {
    const inFeature = new Set(joinFeatures(plan.data?.prds ?? [], del.data?.lanes ?? []).flatMap((f) => f.issues.map((i) => i.n)));
    return (del.data?.lanes ?? [])
      .flatMap((l) => l.cards)
      .filter((c) => !inFeature.has(c.n))
      .map((c) => ({ ...c, status: issueStatus(c) }));
  }, [plan.data, del.data]);

  return (
    <div className="content-inner">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={link(routes.features)} style={{ textDecoration: 'none' }}>Features</Link><Icon n="right" s={13} /><span>Other issues</span>
      </nav>
      <div className="page-head">
        <div className="grow">
          <h1>Other issues</h1>
          <p className="sub">Open issues in {repo} that are not part of a feature: no epic, or an epic with no PRD in this repo.</p>
        </div>
      </div>
      <BoardStatus meta={del.data} />
      {del.isError && !del.data ? (
        <EmptyState icon="alert" title="Issues unavailable" actions={<Button onClick={() => del.refetch()}>Retry</Button>}>{del.error.message}</EmptyState>
      ) : !snapshotsReady(plan.data, del.data) ? (
        <div className="stack" aria-busy="true"><p className="muted" role="status">Loading issues…</p><div className="skel" style={{ height: 120 }} /></div>
      ) : issues.length ? (
        <IssueTable issues={issues} repo={repo} />
      ) : (
        <EmptyState icon="check" title="Nothing outside a feature">Every open issue here belongs to a feature.</EmptyState>
      )}
    </div>
  );
}
