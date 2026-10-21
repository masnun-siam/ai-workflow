import { useState } from 'react';
import { Link } from 'react-router-dom';
import { usePeerReviewOffers, useReviewLens, useReviewRounds, useStartReview } from '../api/hooks';
import { Banner, Button, Chip, Icon, toast, type IconName } from '../components';
import type { Tone } from '../lib/vocab';
import type { Feature } from '../lib/features';
import { routes } from '../lib/routes';
import { LENSES, lensName, STAGES, stageIdx } from '../lib/vocab';
import { useRepo } from '../shell/useRepo';
import { useStepRunner } from './useStepRunner';

const V: Record<string, [Tone, string, IconName]> = {
  approve: ['ship', 'Approves', 'check'],
  changes: ['review', 'Wants changes', 'alert'],
  waiting: ['build', 'Reviewing', 'clock'],
  failed: ['bad', 'Failed', 'x'],
};

export function ReviewTab({ f, repo }: { f: Feature; repo: string }) {
  const p = f.panel;
  const offers = usePeerReviewOffers().data;
  const choices = offers?.kinds?.custom ?? LENSES;
  const [pick, setPick] = useState<string[] | null>(null);
  const picked = pick ?? offers?.default ?? ['critical', 'cto', 'security', 'qa'];
  const start = useStartReview();
  const lens = useReviewLens();
  const rounds = useReviewRounds();
  const { run } = useStepRunner(f, repo);
  const { link } = useRepo();

  if (!p) {
    const draft = f.stage === 'draft';
    return (
      <div className="box" style={{ maxWidth: 640 }}>
        <h3>Run the peer review panel</h3>
        <p className="muted">Each lens reviews the PRD on its own. Claude revises after every round until all approve, up to {offers?.max_rounds ?? 5} rounds.</p>
        <div className="lens-row" role="group" aria-label="Lenses">
          {choices.map((l) => (
            <button key={l} type="button" className={`lens ${picked.includes(l) ? 'on' : ''}`} aria-pressed={picked.includes(l)} onClick={() => setPick(picked.includes(l) ? picked.filter((x) => x !== l) : [...picked, l])}>{lensName(l)}</button>
          ))}
        </div>
        <div>
          <Button variant="primary" disabled={!picked.length || !draft || start.isPending} onClick={() => start.mutate({ repo, artifact: f.prd.abs_path, lenses: picked }, { onSuccess: () => toast('Peer review started') })}>
            Start review with {picked.length} lenses
          </Button>
        </div>
        {!draft ? <p className="faint" style={{ fontSize: 13 }}>Peer review runs on draft PRDs. This one is {STAGES[stageIdx(f.stage)].label.toLowerCase()}.</p> : null}
      </div>
    );
  }

  const capped = p.state === 'cap reached';
  const max = p.max_rounds ?? offers?.max_rounds ?? 0;
  return (
    <div className="stack">
      <div className="row wrap">
        <h2>Round {p.round} of {max || '?'}</h2>
        {p.state === 'running' ? <Chip tone="build" live>Running</Chip> : null}
        {capped ? <Chip tone="you">Needs your decision</Chip> : null}
        {p.state === 'approved' ? <Chip tone="ship">All approve</Chip> : null}
        {p.state === 'failed' ? <Chip tone="bad">Failed</Chip> : null}
        <span className="grow" />
        {p.root_session ? <Link className="btn sm ghost" to={link(routes.session(p.root_session))}>Open root session</Link> : null}
      </div>
      {p.state === 'failed' && p.reason ? <Banner tone="bad" icon="alert"><p>{p.reason}</p></Banner> : null}
      {capped ? (
        <Banner
          tone="you"
          icon="alert"
          action={
            <div className="row wrap">
              <Button sm disabled={rounds.isPending} onClick={() => rounds.mutate({ panel: p.id, add: 2 }, { onSuccess: () => toast('Running 2 more rounds') })}>Run 2 more rounds</Button>
              <Button sm onClick={() => run({ kind: 'approve' })}>Approve anyway</Button>
            </div>
          }
        >
          <p><b>The panel did not converge in {max} rounds.</b> {p.reason ?? ''}</p>
        </Banner>
      ) : null}
      <div className="tbl-wrap">
        <table className="tbl">
          <thead><tr><th>Lens</th><th>Verdict</th><th /></tr></thead>
          <tbody>
            {Object.entries(p.lenses).map(([l, v]) => {
              const [tone, label, icon] = V[v] ?? (['muted', v, 'clock'] as [Tone, string, IconName]);
              return (
                <tr key={l}>
                  <td style={{ fontWeight: 600 }}>{lensName(l)}</td>
                  <td><Chip tone={tone} live={v === 'waiting'}><Icon n={icon} s={12} />{label}</Chip></td>
                  <td style={{ textAlign: 'right' }}>
                    {v === 'failed' ? (
                      <>
                        <Button sm disabled={lens.isPending} aria-label={`Re-run ${lensName(l)}`} onClick={() => lens.mutate({ panel: p.id, lens: l, action: 'rerun' })}>Re-run</Button>{' '}
                        <Button sm variant="ghost" disabled={lens.isPending} aria-label={`Drop ${lensName(l)}`} onClick={() => lens.mutate({ panel: p.id, lens: l, action: 'drop' })}>Drop</Button>
                      </>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
