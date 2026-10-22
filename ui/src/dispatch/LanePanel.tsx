// One lane in detail: where it is, what it needs, its actions, a message box and its live session.
import { useEffect, useRef, useState } from 'react';
import { useDispatchLane, useLaneAction, useSession, useTranscript } from '../api/hooks';
import type { Dispatch, Lane, LaneAction } from '../api/types';
import { Button, Chip, Icon, LinkButton, MoreMenu, useConfirm, useToast, type MenuEntry } from '../components';
import { clockText, fmtTokens, money } from '../lib/format';
import { routes } from '../lib/routes';
import { Transcript } from '../session/Transcript';
import { isLive } from '../lib/vocab';
import { STAGE, STEPS, ghIssue, ghPr, issueNo, nowLine, secs } from './vocab';

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
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // follow the tail inside the box only: the transcript's own auto-scroll would move the whole page
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [events.length]);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row"><b className="grow">What the session is doing</b><LinkButton sm variant="ghost" to={routes.session(id)}>Open session</LinkButton></div>
      <div className="dsp-transcript" ref={box}>
        <Transcript events={events.slice(-80)} live={false} working={s?.outcome === 'running'} />
      </div>
    </div>
  );
}

function HerdrPane({ d, l }: { d: Dispatch; l: Lane }) {
  const q = useDispatchLane(d.id, l.key, !!l.tab && l.stage !== 'closed');
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row"><b className="grow">What the herdr tab shows</b><span className="faint" style={{ fontSize: 12 }}>tab issue-{l.n}, refreshed every 3 s</span></div>
      {q.isError ? <p className="muted">{q.error.message}</p> : <pre className="dsp-pane">{q.data?.text?.split('\n').slice(-60).join('\n') || 'Reading the tab…'}</pre>}
    </div>
  );
}

export function LanePanel({ d, l, onClose }: { d: Dispatch; l: Lane; onClose: () => void }) {
  const act = useLaneAction();
  const confirm = useConfirm();
  const toast = useToast();
  const [msg, setMsg] = useState('');
  const live = l.stage !== 'queued' && l.stage !== 'closed' && l.stage !== 'skipped';
  const run = (action: LaneAction, done: string, text?: string) =>
    act.mutate({ id: d.id, lane: l.key, action, text }, { onSuccess: () => toast(done) });
  const skip = async () => {
    if (await confirm({ title: `Skip ${issueNo(l.key)}?`, body: 'Its session closes and the issues that wait for it stay waiting. Retry brings it back.', okLabel: 'Skip issue', danger: true }))
      run('skip', 'Skipped');
  };
  const mergeNow = async () => {
    if (await confirm({ title: `Merge PR #${l.pr}?`, body: 'A merge commit at the next check (within 30 s), even if CI, review or the grind are not done yet. GitHub still applies its own rules.', okLabel: 'Merge' }))
      run('merge', 'Merge requested');
  };
  const send = () => {
    if (!msg.trim()) return;
    run('send', 'Sent to the lane', msg.trim());
    setMsg('');
  };
  const sendable = !!(l.session || l.tab) && l.stage !== 'closed';

  const now = nowLine(l, d.lanes);
  const canMerge = !!l.pr && ['merge_gate', 'awaiting_merge'].includes(l.stage);
  const primary =
    now.ask === 'merge' ? <Button variant="you" onClick={() => void mergeNow()}><Icon n="merge" />Merge PR #{l.pr}</Button>
    : now.ask === 'retry' ? <Button variant="primary" onClick={() => run('retry', 'Retrying')}><Icon n="refresh" />Retry</Button>
    : l.paused ? <Button variant="primary" onClick={() => run('resume', 'Resumed')}><Icon n="play" />Resume</Button>
    : null;
  const more: MenuEntry[] = [
    ...(live && !l.paused ? [{ label: 'Pause this issue', icon: 'pause' as const, onSelect: () => run('pause', 'Paused') }] : []),
    ...(canMerge && now.ask !== 'merge' ? [{ label: `Merge PR #${l.pr} now`, icon: 'merge' as const, onSelect: () => void mergeNow() }] : []),
    ...(l.pr && !['closed', 'followups'].includes(l.stage)
      ? [{ label: l.hold_merge ? 'Let it merge' : 'Hold the merge', icon: 'lock' as const, onSelect: () => run(l.hold_merge ? 'unhold' : 'hold', l.hold_merge ? 'It will merge when ready' : 'Merge held') }]
      : []),
    ...(now.ask !== 'retry' && l.stage !== 'closed' && l.stage !== 'queued' ? [{ label: 'Retry in a new session', icon: 'refresh' as const, onSelect: () => run('retry', 'Retrying') }] : []),
    { label: 'Open the issue on GitHub', icon: 'github' as const, onSelect: () => window.open(ghIssue(l.repo, l.n), '_blank', 'noopener') },
    ...(l.pr ? [{ label: `Open PR #${l.pr} on GitHub`, icon: 'pr' as const, onSelect: () => window.open(ghPr(l.repo, l.pr!), '_blank', 'noopener') }] : []),
    ...(l.stage !== 'closed' && l.stage !== 'skipped' ? ['sep' as const, { label: 'Skip this issue', icon: 'x' as const, danger: true, onSelect: () => void skip() }] : []),
  ];

  return (
    <aside className="dsp-lane" aria-label={`Lane ${issueNo(l.key)}`}>
      <div className="row" style={{ alignItems: 'flex-start' }}>
        <div className="grow" style={{ minWidth: 0 }}>
          <div className="faint" style={{ fontSize: 12.5 }}><span className="dsp-ref">{issueNo(l.key)}</span> in {l.repo}</div>
          <h2 style={{ fontSize: 16 }}>{l.title || issueNo(l.key)}</h2>
        </div>
        <MoreMenu items={more} label="Issue actions" />
        <Button variant="ghost" icon sm aria-label="Close lane" onClick={onClose}><Icon n="x" /></Button>
      </div>
      <div className={`dsp-lane-now t-${now.tone}`}>
        <div className="row" style={{ gap: 8 }}>
          <Chip tone={STAGE[l.stage].tone} live={live && !now.ask && !l.paused}>{STAGE[l.stage].label}</Chip>
          <b className="grow">{now.text}</b>
        </div>
        {primary ? <div className="row">{primary}</div> : null}
      </div>
      <Stepper l={l} />
      <dl className="facts">
        <dt>Waits for</dt><dd>{l.deps.length ? l.deps.map(issueNo).join(', ') : 'nothing'}</dd>
        <dt>Pull request</dt><dd>{l.pr ? <a href={ghPr(l.repo, l.pr)} target="_blank" rel="noopener noreferrer">#{l.pr}</a> : 'not opened yet'}</dd>
        {l.limited_until && l.limited_until * 1000 > Date.now() ? <><dt>Resumes at</dt><dd>{clockText(l.limited_until)}</dd></> : null}
        <dt>Time</dt><dd>{l.usage.seconds ? secs(l.usage.seconds) : 'not started'}</dd>
        {d.runner === 'headless' && l.usage.cost > 0 ? <><dt>Spent</dt><dd>{money(l.usage.cost)}, {fmtTokens(l.usage.tokens)} tokens</dd></> : null}
      </dl>
      {sendable ? (
        <form className="row" onSubmit={(e) => { e.preventDefault(); send(); }}>
          <input className="f" placeholder={`Message the session working on ${issueNo(l.key)}`} aria-label="Message to the session" value={msg} maxLength={2000} onChange={(e) => setMsg(e.target.value)} />
          <Button sm type="submit" variant="primary" disabled={!msg.trim()} aria-label="Send"><Icon n="send" /></Button>
        </form>
      ) : null}
      {l.session ? <HeadlessSession id={l.session} /> : l.tab ? <HerdrPane d={d} l={l} /> : <p className="faint">{l.stage === 'queued' ? 'No session yet. It starts by itself when its turn comes.' : 'No session is attached.'}</p>}
    </aside>
  );
}
