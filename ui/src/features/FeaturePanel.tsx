import { useMemo } from 'react';
import { useDelivery, usePlanning } from '../api/hooks';
import { LinkButton } from '../components';
import { useEpicDispatch } from '../dispatch/useOwner';
import { needsYou } from '../dispatch/vocab';
import { issueBuckets, joinFeatures, type Feature } from '../lib/features';
import { repoLink } from '../lib/repo';
import { routes } from '../lib/routes';
import { STAGES, stageIdx } from '../lib/vocab';
import { PanelFrame } from '../panels/DetailPanel';
import { usePanel } from '../panels/PanelContext';
import { NextStepBox } from './NextStepBox';

const short = (slug: string) => slug.split('/').pop() ?? slug;

function Body({ f, repo }: { f: Feature; repo: string }) {
  const panel = usePanel();
  const live = useEpicDispatch(repo, f.epic);
  const at = stageIdx(f.stage);
  const buckets = issueBuckets(f.issues, new Set((live?.d.lanes ?? []).filter(needsYou).map((l) => l.n)));
  return (
    <PanelFrame
      title={f.title}
      subtitle={<>{short(repo)}, {f.epic ? `epic #${f.epic}` : 'no epic yet'}{f.prd.account ? `, runs on ${f.prd.account}` : ''}</>}
      head={<LinkButton sm to={repoLink(repo, routes.feature(f.slug))}>Open the feature page</LinkButton>}
    >
      <ol className="fp-stages" aria-label={`Stage: ${STAGES[at].label}`}>
        {STAGES.map((s, k) => <li key={s.id} className={k < at ? 'past' : k === at ? 'now' : ''} aria-current={k === at ? 'step' : undefined}>{s.label}</li>)}
      </ol>
      <NextStepBox f={f} repo={repo} />
      {buckets.length ? buckets.map((b) => (
        <details key={b.id} className="fp-group" open={b.id !== 'merged'}>
          <summary><i className={`s-${b.id}`} />{b.label} <span>{b.items.length}</span></summary>
          {b.items.map((i) => (
            <button key={i.n} type="button" className="fp-issue" onClick={() => panel.open({ kind: 'issue', repo, n: i.n })}>
              <span className="n">#{i.n}</span>
              <span>{i.title}</span>
              {i.blocked_by.length ? <em>waits for {i.blocked_by.length}</em> : null}
            </button>
          ))}
        </details>
      )) : <p className="muted" style={{ margin: 0 }}>No issues yet. They appear here once the PRD is approved and broken into tasks.</p>}
    </PanelFrame>
  );
}

/** One feature in the detail panel: where it stands, its next step and its issues, without leaving the list. */
export function FeaturePanel({ repo, slug }: { repo: string; slug: string }) {
  const plan = usePlanning(repo);
  const del = useDelivery(repo);
  const f = useMemo(() => joinFeatures(plan.data?.prds ?? [], del.data?.lanes ?? []).find((x) => x.slug === slug), [plan.data, del.data, slug]);
  if (f) return <Body f={f} repo={repo} />;
  return <PanelFrame title="Feature"><p className="muted" role="status">{plan.isPending || del.isPending ? 'Loading…' : 'Feature not found.'}</p></PanelFrame>;
}
