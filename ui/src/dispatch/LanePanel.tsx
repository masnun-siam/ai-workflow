// One lane in detail: where it is, what it needs, its actions, a message box and its live session.
import { useState } from 'react';
import { useDispatchLane, useLaneAction, useSession, useTranscript } from '../api/hooks';
import type { Dispatch, Lane, LaneAction } from '../api/types';
import { Banner, Button, Chip, ExtButton, Icon, LinkButton, useConfirm, useToast } from '../components';
import { clockText, fmtTokens, money } from '../lib/format';
import { routes } from '../lib/routes';
import { Transcript } from '../session/Transcript';
import { isLive } from '../lib/vocab';
import { STAGE, STEPS, ghIssue, ghPr, issueNo, laneNote, secs } from './vocab';

function Stepper({ l }: { l: Lane }) {
  const step = STAGE[l.stage].step;
  return (
    <ol className="dsp-steps" aria-label="Lane progress">
      {STEPS.map((s, i) => {
        const state = l.stage === 'closed' || i + 1 < step ? 'done' : i + 1 === step ? 'now' : '';
        return <li key={s} className={state} aria-current={state === 'now' ? 'step' : undefined}>{state === 'done' ? <Icon n="check" s={12} /> : null}{s}</li>;
      })}
    </ol>
  );
}

function HeadlessSession({ id }: { id: string }) {
  const s = useSession(id).data;
  const live = !!s && isLive(s.outcome);
  const { events } = useTranscript(id, live);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row"><b className="grow">Session</b><LinkButton sm variant="ghost" to={routes.session(id)}>Open full session</LinkButton></div>
      <Transcript events={events.slice(-80)} live={live} working={s?.outcome === 'running'} />
    </div>
  );
}

function HerdrPane({ d, l }: { d: Dispatch; l: Lane }) {
  const q = useDispatchLane(d.id, l.key, !!l.tab && l.stage !== 'closed');
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row"><b className="grow">herdr tab</b><span className="faint" style={{ fontSize: 12 }}>issue-{l.n}, refreshed every 3 s</span></div>
      {q.isError ? <p className="muted">{q.error.message}</p> : <pre className="dsp-pane">{q.data?.text?.split('\n').slice(-60).join('\n') || 'Reading the tab…'}</pre>}
    </div>
  );
}

export function LanePanel({ d, l, onClose }: { d: Dispatch; l: Lane; onClose: () => void }) {
  const act = useLaneAction();
  const confirm = useConfirm();
  const toast = useToast();
  const [msg, setMsg] = useState('');
  const note = laneNote(l);
  const live = l.stage !== 'queued' && l.stage !== 'closed' && l.stage !== 'skipped';
  const run = (action: LaneAction, done: string, text?: string) =>
    act.mutate({ id: d.id, lane: l.key, action, text }, { onSuccess: () => toast(done) });
  const skip = async () => {
    if (await confirm({ title: `Skip ${issueNo(l.key)}?`, body: 'Its session closes and the issues that depend on it wait. Retry brings it back.', okLabel: 'Skip lane', danger: true }))
      run('skip', 'Lane skipped');
  };
  const mergeNow = async () => {
    if (await confirm({ title: `Merge PR #${l.pr} now?`, body: 'This merges with a merge commit at the next tick, even if the gate is not met. GitHub still enforces its own rules.', okLabel: 'Merge now' }))
      run('merge', 'Merge requested');
  };
  const send = () => {
    if (!msg.trim()) return;
    run('send', 'Sent to the lane', msg.trim());
    setMsg('');
  };
  const sendable = !!(l.session || l.tab) && l.stage !== 'closed';

  return (
    <aside className="dsp-lane" aria-label={`Lane ${issueNo(l.key)}`}>
      <div className="row" style={{ alignItems: 'flex-start' }}>
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="faint mono" style={{ fontSize: 12 }}>{l.key}</div>
          <h2 style={{ fontSize: 16 }}>{l.title || issueNo(l.key)}</h2>
        </div>
        <Button variant="ghost" icon sm aria-label="Close lane" onClick={onClose}><Icon n="x" /></Button>
      </div>
      <div className="row wrap" style={{ gap: 6 }}>
        <Chip tone={STAGE[l.stage].tone} live={live && !note}>{STAGE[l.stage].label}</Chip>
        {l.paused ? <Chip tone="review">Paused</Chip> : null}
        {l.hold_merge ? <Chip tone="muted">Merge held</Chip> : null}
      </div>
      <Stepper l={l} />
      {note && note.tone !== 'muted' ? <Banner tone={note.tone === 'you' ? 'you' : note.tone === 'bad' ? 'bad' : 'review'} icon="alert">{note.text}</Banner> : null}
      <dl className="facts">
        {l.stage === 'merge_gate' && l.gate ? <><dt>Gate</dt><dd>{l.gate}</dd></> : null}
        <dt>Depends on</dt><dd>{l.deps.length ? l.deps.map(issueNo).join(', ') : 'nothing'}</dd>
        <dt>Pull request</dt><dd>{l.pr ? <a href={ghPr(l.repo, l.pr)} target="_blank" rel="noopener noreferrer">#{l.pr}</a> : 'not yet'}</dd>
        {l.limited_until && l.limited_until * 1000 > Date.now() ? <><dt>Resumes</dt><dd>{clockText(l.limited_until)}</dd></> : null}
        <dt>Time</dt><dd>{l.usage.seconds ? secs(l.usage.seconds) : '—'}</dd>
        <dt>Cost</dt><dd>{d.runner === 'herdr' ? 'not reported by herdr tabs' : `${money(l.usage.cost)} · ${fmtTokens(l.usage.tokens)} tokens`}</dd>
      </dl>
      <div className="row wrap" style={{ gap: 6 }}>
        {l.paused ? <Button sm onClick={() => run('resume', 'Lane resumed')}><Icon n="play" />Resume</Button> : live ? <Button sm onClick={() => run('pause', 'Lane paused')}><Icon n="pause" />Pause</Button> : null}
        {l.needs_you || l.held || l.stage === 'skipped' ? <Button sm onClick={() => run('retry', 'Retrying the lane')}><Icon n="refresh" />Retry</Button> : null}
        {l.pr && ['merge_gate', 'awaiting_merge'].includes(l.stage) ? <Button sm variant="primary" onClick={() => void mergeNow()}><Icon n="merge" />Merge now</Button> : null}
        {l.pr && l.stage !== 'closed' && l.stage !== 'followups' ? (
          <Button sm onClick={() => run(l.hold_merge ? 'unhold' : 'hold', l.hold_merge ? 'Merge released' : 'Merge held')}>{l.hold_merge ? 'Release merge' : 'Hold merge'}</Button>
        ) : null}
        {l.stage !== 'closed' && l.stage !== 'skipped' ? <Button sm variant="ghost" onClick={() => void skip()}>Skip</Button> : null}
        <ExtButton sm variant="ghost" href={ghIssue(l.repo, l.n)}><Icon n="github" />Issue</ExtButton>
      </div>
      {sendable ? (
        <form className="row" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <input className="f" placeholder={`Tell ${issueNo(l.key)}…`} aria-label="Message to the lane" value={msg} maxLength={2000} onChange={(e) => setMsg(e.target.value)} />
          <Button sm type="submit" variant="primary" disabled={!msg.trim()} aria-label="Send"><Icon n="send" /></Button>
        </form>
      ) : null}
      {l.session ? <HeadlessSession id={l.session} /> : l.tab ? <HerdrPane d={d} l={l} /> : <p className="faint">{l.stage === 'queued' ? 'No session yet: the lane starts once its blockers are done and a slot is free.' : 'No session is attached to this lane.'}</p>}
    </aside>
  );
}
