// One dispatch, read top to bottom: what is building now, what starts next and why, what is done; the picked lane or the activity feed beside it.
import { useEffect, useMemo, useState, type HTMLAttributes } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useDispatch, useDispatchSeen, useDispatchSettings, useDispatchState, useEndAction, useLaneAction, useSessions } from '../api/hooks';
import type { Dispatch, DispatchEvent, EndAction, Lane } from '../api/types';
import { Banner, Button, Chip, EmptyState, Icon, type IconName, useConfirm, useListSelection, useToast } from '../components';
import { KeyScope } from '../shell/shortcuts';
import { clockText, money, shortRepo } from '../lib/format';
import { routes } from '../lib/routes';
import { LanePanel } from '../dispatch/LanePanel';
import { SettingsFields } from '../dispatch/SettingsFields';
import { ACTIVE, DSTATE, STAGE, STEPS, counts, dispatchHeading, dispatchRepo, epicNo, eventText, issueNo, levels, nowLine, secs, type LaneAsk } from '../dispatch/vocab';
import '../dispatch/dispatch.css';

const KIND_ICON: Record<string, IconName> = { needs_you: 'alert', held: 'alert', awaiting_merge: 'merge', merged: 'check', finished: 'check' };

/** Lanes that need you, each with its one action. Silent when nothing does. */
function NeedsYou({ d, onPick, selected }: { d: Dispatch; onPick: (k: string) => void; selected: string | null }) {
  const act = useLaneAction();
  const confirm = useConfirm();
  const toast = useToast();
  const asks = d.lanes.map((l) => ({ l, now: nowLine(l, d.lanes) })).filter((x) => x.now.ask);
  if (!asks.length) return null;
  const go = async (l: Lane, ask: LaneAsk) => {
    if (ask === 'open') return onPick(l.key);
    if (ask === 'merge' && !(await confirm({ title: `Merge PR #${l.pr}?`, body: 'A merge commit within 30 s. Then the issue is closed and cleaned up.', okLabel: 'Merge' }))) return;
    act.mutate({ id: d.id, lane: l.key, action: ask }, { onSuccess: () => toast(ask === 'merge' ? 'Merge requested' : 'Retrying') });
  };
  const LABEL: Record<LaneAsk, string> = { merge: 'Merge', open: 'Answer', retry: 'Retry' };
  const KEY = { merge: 'm', open: 'a', retry: 'r' } as const;
  return (
    <section className="dsp-asks" aria-label="Needs you">
      <h2>{asks.length === 1 ? 'One issue needs you' : `${asks.length} issues need you`}</h2>
      <ul>
        {asks.map(({ l, now }) => (
          <li key={l.key}>
            <button type="button" className="linkish dsp-ask-t" onClick={() => onPick(l.key)}>
              <span className="dsp-ref">{issueNo(l.key)}</span> {l.title}
            </button>
            <span className={`dsp-c t-${now.tone}`}>{now.text}</span>
            <KeyScope level="row" active={selected === l.key} name={issueNo(l.key)}>
              <Button sm variant={now.ask === 'retry' ? 'default' : 'you'} shortcut={KEY[now.ask!]} onClick={() => void go(l, now.ask!)}>{LABEL[now.ask!]}</Button>
            </KeyScope>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Feed({ events, onPick }: { events: DispatchEvent[]; onPick: (k: string) => void }) {
  const [all, setAll] = useState(false);
  const shown = [...events].reverse().filter((e) => all || e.kind !== 'settings');
  return (
    <section className="dsp-feed" aria-label="Activity">
      <div className="row"><h2 className="grow" style={{ fontSize: 14 }}>Activity</h2>
        <label className="row faint" style={{ gap: 4, fontSize: 12 }}><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} />Settings changes</label>
      </div>
      {shown.length ? (
        <ol>
          {shown.slice(0, 150).map((e, i) => (
            <li key={`${e.at}-${i}`} className={`k-${e.kind}`}>
              <span className="dsp-ev-ic" aria-hidden="true">{KIND_ICON[e.kind] ? <Icon n={KIND_ICON[e.kind]} s={12} /> : null}</span>
              <span className="faint mono">{clockText(e.at)}</span>
              <span>
                {e.lane ? <><button type="button" className="linkish dsp-ref" onClick={() => onPick(e.lane!)}>{issueNo(e.lane)}</button> </> : null}
                {eventText(e)}
              </span>
            </li>
          ))}
        </ol>
      ) : <p className="faint">Nothing yet.</p>}
    </section>
  );
}

function EndPanel({ d }: { d: Dispatch }) {
  const end = useEndAction();
  const toast = useToast();
  const fb = d.settings.feature_branch;
  const base = d.settings.base_branch;
  const prs = Object.entries(d.final_prs ?? {});
  const go = (action: EndAction, msg: string) => end.mutate({ id: d.id, action }, { onSuccess: () => toast(msg) });
  return (
    <section className="dsp-end" aria-label="What next">
      <div className="row"><Icon n="check" /><h2 className="grow" style={{ fontSize: 15 }}>{d.epic ? 'Every issue is done. What next?' : 'Every issue is done.'}</h2></div>
      {d.epic ? <>
      <p className="muted">Nothing here runs by itself. QA files each bug it finds as a new issue of the epic, and new issues join this dispatch.</p>
      <div className="row wrap" style={{ gap: 8 }}>
        {fb && !prs.length ? <Button variant="primary" shortcut="o" onClick={() => go('open-pr', 'Opening the PR')}><Icon n="pr" />Open PR from {fb} into {base ?? 'the default branch'}</Button> : null}
        <Button onClick={() => go('qa', 'QA session starting')}><Icon n="eye" />Run QA{fb ? ` on ${fb}` : ''}</Button>
        {prs.length ? <Button onClick={() => go('grind-pr', 'Grind starting')}><Icon n="refresh" />Grind the final PR</Button> : null}
      </div>
      {prs.length ? (
        <ul className="stack" style={{ gap: 4, margin: 0, paddingLeft: 18 }}>
          {prs.map(([repo, url]) => <li key={repo}><a href={url} target="_blank" rel="noopener noreferrer">{shortRepo(repo)}: {url.replace(/^.*\/pull\//, 'PR #')}</a></li>)}
        </ul>
      ) : null}
      </> : null}
    </section>
  );
}

type RowProps = (key: string) => HTMLAttributes<HTMLElement> & { ref: (el: HTMLElement | null) => void };
type Rows = { lanes: Lane[]; all: Lane[]; picked: string | null; onPick: (k: string) => void; rowProps: RowProps; short: (t: string) => string; label: (l: Lane) => string };

/** Lanes by where they stand: building now, up next (ready before blocked, then by wave), done (latest first). */
function groups(lanes: Lane[]) {
  const lv = levels(lanes);
  const ready = (l: Lane) => l.deps.every((k) => (lanes.find((x) => x.key === k)?.stage ?? 'closed') === 'closed');
  const now = lanes.filter((l) => ACTIVE.includes(l.stage));
  const next = lanes.filter((l) => l.stage === 'queued').sort((a, b) => Number(ready(b)) - Number(ready(a)) || lv[a.key] - lv[b.key] || a.n - b.n);
  const done = lanes.filter((l) => l.stage === 'closed' || l.stage === 'skipped').sort((a, b) => (b.ended_at ?? 0) - (a.ended_at ?? 0));
  return { now, next, done };
}

const laneProps = (l: Lane, { picked, onPick, rowProps }: Pick<Rows, 'picked' | 'onPick' | 'rowProps'>) => ({
  ...(rowProps(l.key) as HTMLAttributes<HTMLButtonElement>),
  type: 'button' as const,
  'data-lane': l.key,
  'aria-pressed': picked === l.key,
  onClick: () => onPick(l.key),
});

/** One card per lane at work, with the four steps it walks and how long it has been at it. */
function BuildingNow({ lanes, all, picked, onPick, rowProps, short, label, max }: Rows & { max: number }) {
  if (!lanes.length) return null;
  return (
    <section className="dsp-sec" aria-label="Building now">
      <h2>Building now <small>{lanes.length} of {max} at a time</small></h2>
      {lanes.map((l) => {
        const now = nowLine(l, all);
        const step = STAGE[l.stage].step;
        return (
          <button key={l.key} className={`dsp-live${picked === l.key ? ' on' : ''}${now.ask ? ' you' : ''}`} {...laneProps(l, { picked, onPick, rowProps })}>
            <span className="dsp-live-t"><span className="dsp-ref">{label(l)}</span><b>{short(l.title || issueNo(l.key))}</b>
              {l.started_at ? <span className="dsp-num">{secs(Math.max(0, Math.round(Date.now() / 1000 - l.started_at)))}</span> : null}</span>
            <span className="dsp-track" role="img" aria-label={`${STAGE[l.stage].label}, step ${step} of 4`}>
              {STEPS.slice(0, 4).map((s, i) => <span key={s} className={i + 1 < step ? 'ok' : i + 1 === step ? 'at' : ''}>{s}</span>)}
            </span>
            <span className="dsp-live-f"><span className={`dsp-c t-${now.tone}`}>{now.ask ? <Icon n="alert" s={12} /> : null} {now.text}</span>
              {l.usage.cost > 0 ? <span className="dsp-num">{money(l.usage.cost)}</span> : null}</span>
          </button>
        );
      })}
    </section>
  );
}

/** Waiting lanes in the order they will start, each with why it is waiting. */
function UpNext({ lanes, all, picked, onPick, rowProps, short, label }: Rows) {
  if (!lanes.length) return null;
  return (
    <section className="dsp-sec" aria-label="Up next">
      <h2>Up next <small>{lanes.length} waiting</small></h2>
      <ul className="dsp-rows">
        {lanes.map((l) => {
          const now = nowLine(l, all);
          const blocked = now.text.startsWith('Starts after');
          return (
            <li key={l.key}><button className={`dsp-row${picked === l.key ? ' on' : ''}${blocked ? '' : ' ready'}`} {...laneProps(l, { picked, onPick, rowProps })}>
              <span className="dsp-ref">{label(l)}</span><span className="dsp-row-t">{short(l.title || issueNo(l.key))}</span><span className="dsp-why">{now.text}</span>
            </button></li>
          );
        })}
      </ul>
    </section>
  );
}

/** Finished lanes, latest first: the PR, how long it took and what it cost. */
function Done({ lanes, picked, onPick, rowProps, short, label, headless }: Rows & { headless: boolean }) {
  if (!lanes.length) return null;
  const merged = lanes.filter((l) => l.stage === 'closed').length;
  return (
    <section className="dsp-sec" aria-label="Done">
      <h2>Done <small>{merged} merged{lanes.length > merged ? `, ${lanes.length - merged} skipped` : ''}</small></h2>
      <ul className="dsp-rows">
        {lanes.map((l) => {
          const took = l.started_at && l.ended_at ? Math.round(l.ended_at - l.started_at) : l.usage.seconds;
          return (
            <li key={l.key}><button className={`dsp-row done${picked === l.key ? ' on' : ''}`} {...laneProps(l, { picked, onPick, rowProps })}>
              <span className="dsp-ref">{label(l)}</span><span className="dsp-row-t">{short(l.title || issueNo(l.key))}</span>
              <span className={l.stage === 'closed' ? 'dsp-pr' : 'dsp-why'}>{l.stage === 'closed' ? (l.pr ? `PR #${l.pr}` : 'Done') : 'Skipped'}</span>
              <span className="dsp-num">{took ? secs(took) : ''}</span>
              <span className="dsp-num">{headless && l.usage.cost > 0 ? money(l.usage.cost) : ''}</span>
            </button></li>
          );
        })}
      </ul>
    </section>
  );
}

const TICK: Record<string, number> = { closed: 0, skipped: 1, queued: 3 };

export function DispatchPage() {
  const { id = '' } = useParams();
  const [sp, setSp] = useSearchParams();
  const q = useDispatch(id);
  const save = useDispatchSettings();
  const state = useDispatchState();
  const seen = useDispatchSeen();
  const confirm = useConfirm();
  const toast = useToast();
  const limits = useSessions().data?.limits ?? {};
  const [showSettings, setShowSettings] = useState(false);
  const picked = sp.get('lane');
  const pick = (k: string | null) => {
    const n = new URLSearchParams(sp);
    if (k && k !== picked) n.set('lane', k);
    else n.delete('lane');
    setSp(n, { replace: true });
  };
  const d = q.data;
  const g = useMemo(() => groups(d?.lanes ?? []), [d?.lanes]);
  const selection = useListSelection({
    keys: [...g.now, ...g.next, ...g.done].map((l) => l.key),
    onOpen: (k) => k !== picked && pick(k),
    onMove: (k) => picked && pick(k),
    reset: id,
  });
  useEffect(() => {
    // Esc closes the lane panel and leaves its lane selected and focused, unless a dialog or menu is on top.
    if (!picked) return;
    const h = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented || document.querySelector('[role=dialog],[role=alertdialog],[role=menu]')) return;
      pick(null);
      document.querySelector<HTMLElement>(`[data-lane="${CSS.escape(picked)}"]`)?.focus();
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [picked, sp]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (d?.state === 'done') seen.mutate(d.id); // opening a finished dispatch clears its Inbox row
  }, [d?.id, d?.state]); // eslint-disable-line react-hooks/exhaustive-deps
  const c = useMemo(() => (d ? counts(d) : null), [d]);

  if (q.isError) return <div className="content-inner"><EmptyState icon="alert" title="Dispatch not found" actions={<Link className="btn" to={routes.dispatches}>All dispatches</Link>}>{q.error.message}</EmptyState></div>;
  if (!d || !c) return <div className="content-inner" aria-busy="true"><p className="muted" role="status">Loading…</p><div className="skel" style={{ height: 200 }} /></div>;

  const lane = d.lanes.find((l) => l.key === picked) ?? null;
  const st = DSTATE[d.state];
  const live = d.state === 'running' || d.state === 'paused';
  const limited = Object.values(limits).some((x) => x.limited_until && x.limited_until * 1000 > Date.now());
  const head = dispatchHeading(d);
  const short = (t: string) => (head && t.startsWith(`${head}: `) ? t.slice(head.length + 2) : t);
  const multi = new Set(d.lanes.map((l) => l.repo)).size > 1; // a cross-repo epic names the repo on each issue
  const label = (l: Lane) => (multi ? `${shortRepo(l.repo)}${issueNo(l.key)}` : issueNo(l.key));
  const rows = { all: d.lanes, picked, onPick: pick, rowProps: selection.rowProps, short, label };
  const ticks = [...d.lanes].sort((a, b) => (TICK[a.stage] ?? 2) - (TICK[b.stage] ?? 2));
  const asks = d.lanes.some((l) => nowLine(l, d.lanes).ask);
  const cancel = async () => {
    if (await confirm({ title: 'Cancel this dispatch?', body: 'No new issue starts and nothing more is merged. Issues already running keep their sessions and PRs; close them yourself.', okLabel: 'Cancel dispatch', cancelLabel: 'Keep it', danger: true }))
      state.mutate({ id: d.id, state: 'cancelled' }, { onSuccess: () => toast('Dispatch cancelled') });
  };

  return (
    <div className="content-inner dsp-page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={routes.dispatches} style={{ textDecoration: 'none' }}>Dispatches</Link><Icon n="right" s={13} /><span>{d.epic ? `Epic #${epicNo(d.epic)}` : 'Small changes'}</span>
      </nav>
      <div className="page-head">
        <div className="grow" style={{ minWidth: 0 }}>
          <h1>{head}</h1>
          <p className="sub row wrap" style={{ gap: 10 }}>
            <Chip tone={st.tone} live={st.live}>{st.label}</Chip>
            {d.epic ? (
              <a href={`https://github.com/${d.epic.replace('#', '/issues/')}`} target="_blank" rel="noopener noreferrer">{shortRepo(d.epic.split('#')[0])} epic #{epicNo(d.epic)}</a>
            ) : (
              <a href={`https://github.com/${dispatchRepo(d)}`} target="_blank" rel="noopener noreferrer">{dispatchRepo(d)}</a>
            )}
            <span>{d.runner === 'herdr' ? 'in herdr tabs' : 'in background sessions'}, up to {d.settings.max} at a time, grind {d.settings.grind}, CI: {d.settings.ci ?? 'wait'}, {d.settings.auto_merge ? 'merges by itself' : 'you merge'}</span>
          </p>
        </div>
        <div className="row" style={{ gap: 6, flex: 'none' }}>
          <Button aria-expanded={showSettings} onClick={() => setShowSettings(!showSettings)}><Icon n="sliders" />Settings</Button>
          {d.state === 'running' ? <Button onClick={() => state.mutate({ id: d.id, state: 'paused' }, { onSuccess: () => toast('Paused: no new issue starts') })}><Icon n="pause" />Pause</Button> : null}
          {d.state === 'paused' ? <Button variant="primary" shortcut="r" onClick={() => state.mutate({ id: d.id, state: 'running' })}><Icon n="play" />Resume</Button> : null}
          {live ? <Button variant="ghost" shortcut="x" onClick={() => void cancel()}>Cancel</Button> : null}
        </div>
      </div>

      <section className="dsp-progress" aria-label="Progress">
        <div className="dsp-ticks" role="img" aria-label={`${c.closed} of ${c.total} done, ${c.active} building, ${c.queued} waiting`}>
          {ticks.map((l) => <i key={l.key} title={`${issueNo(l.key)} ${STAGE[l.stage].label}`} className={l.stage === 'closed' ? 'done' : l.stage === 'skipped' ? 'skip' : nowLine(l, d.lanes).ask ? 'you' : ACTIVE.includes(l.stage) ? 'run' : ''} />)}
        </div>
        <dl className="dsp-stats">
          <div><dt>done</dt><dd>{c.closed} of {c.total}</dd></div>
          <div><dt>building</dt><dd>{c.active}</dd></div>
          <div><dt>waiting</dt><dd>{c.queued}</dd></div>
          {c.skipped ? <div><dt>skipped</dt><dd>{c.skipped}</dd></div> : null}
          <div><dt>{d.state === 'done' || d.state === 'cancelled' ? 'took' : 'running'}</dt><dd>{secs(d.totals.seconds)}</dd></div>
          {d.runner === 'headless' && d.totals.cost > 0 ? <div><dt>spent</dt><dd>{money(d.totals.cost)}</dd></div> : null}
        </dl>
      </section>

      <NeedsYou d={d} onPick={pick} selected={selection.selected} />
      {d.state === 'paused' ? <Banner tone="review" icon="pause">Paused. Issues already running carry on; no new one starts until you resume.</Banner> : null}
      {limited && live ? <Banner tone="away" icon="clock">A Claude account hit its usage limit. New issues wait, and paused ones resume after the reset.</Banner> : null}
      {showSettings ? (
        <section className="box" aria-label="Dispatch settings">
          <SettingsFields live runner={d.runner} noBranch={!d.epic} value={d.settings} onChange={(p) => save.mutate({ id: d.id, s: p }, { onSuccess: () => toast('Saved: applies from each issue’s next step') })} />
        </section>
      ) : null}
      {d.state === 'done' ? <EndPanel d={d} /> : null}

      <div className="dsp-cols">
        <div className="dsp-main">
          {d.lanes.length ? <>
            <BuildingNow {...rows} lanes={g.now} max={d.settings.max} />
            <UpNext {...rows} lanes={g.next} />
            <Done {...rows} lanes={g.done} headless={d.runner === 'headless'} />
          </> : <EmptyState icon="layers" title="No issues to run">This epic had no open child issues when it started.</EmptyState>}
        </div>
        <div className="dsp-side">
          {lane ? <KeyScope level="panel" active><LanePanel key={lane.key} d={d} l={lane} onClose={() => pick(null)} /></KeyScope> : <>
            {asks || !live ? null : <p className="dsp-calm"><b>Nothing needs you</b>Anything that stops for an answer shows up at the top.</p>}
            <Feed events={d.events ?? []} onPick={pick} />
          </>}
        </div>
      </div>
      <p className="faint" style={{ fontSize: 12 }}>Steer from a terminal too: <span className="mono">aiw dispatch show {d.id}</span></p>
    </div>
  );
}
