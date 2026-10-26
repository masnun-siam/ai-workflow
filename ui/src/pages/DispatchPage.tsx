// One dispatch: live settings, totals, lanes as a graph or a table, the picked lane, the activity feed, end actions.
import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useDispatch, useDispatchSeen, useDispatchSettings, useDispatchState, useEndAction, useLaneAction, useSessions } from '../api/hooks';
import type { Dispatch, DispatchEvent, EndAction, Lane } from '../api/types';
import { Banner, Button, Chip, EmptyState, Icon, useConfirm, useListSelection, useToast } from '../components';
import { KeyScope } from '../shell/shortcuts';
import { clockText, money, shortRepo } from '../lib/format';
import { routes } from '../lib/routes';
import { LanePanel } from '../dispatch/LanePanel';
import { LaneGraph, LaneTable, columns } from '../dispatch/LaneViews';
import { SettingsFields } from '../dispatch/SettingsFields';
import { DSTATE, counts, dispatchHeading, dispatchRepo, epicNo, eventText, issueNo, nowLine, secs, type LaneAsk } from '../dispatch/vocab';
import '../dispatch/dispatch.css';

const VIEW_KEY = 'aiw.dispatch.view';
const readView = () => {
  try {
    return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'graph';
  } catch {
    return 'graph';
  }
};

const KIND_ICON: Record<string, string> = { needs_you: '!', held: '!', awaiting_merge: '↗', merged: '✓', finished: '✓', stage: '·', end: '·' };

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

/** Where the dispatch stands, in one sentence. */
function summary(c: ReturnType<typeof counts>): string {
  const rest = [
    c.active ? `${c.active} in progress` : '',
    c.queued ? `${c.queued} waiting their turn` : '',
    c.skipped ? `${c.skipped} skipped` : '',
  ].filter(Boolean);
  const head = `${c.closed} of ${c.total} issue${c.total === 1 ? '' : 's'} done`;
  return rest.length ? `${head}. ${rest.join(', ').replace(/, ([^,]*)$/, ' and $1')}.` : `${head}.`;
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
              <span className="dsp-ev-ic" aria-hidden="true">{KIND_ICON[e.kind] ?? '·'}</span>
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
  const [view, setView] = useState<'graph' | 'list'>(readView);
  const [showSettings, setShowSettings] = useState(false);
  const picked = sp.get('lane');
  const pick = (k: string | null) => {
    const n = new URLSearchParams(sp);
    if (k && k !== picked) n.set('lane', k);
    else n.delete('lane');
    setSp(n, { replace: true });
  };
  const d = q.data;
  const lanes = d?.lanes ?? [];
  const selection = useListSelection({
    keys: (view === 'graph' ? columns(lanes).flat() : lanes).map((l) => l.key),
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
    try { localStorage.setItem(VIEW_KEY, view); } catch { /* private window */ }
  }, [view]);
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
          <h1>{dispatchHeading(d)}</h1>
          <p className="sub row wrap" style={{ gap: 10 }}>
            <Chip tone={st.tone} live={st.live}>{st.label}</Chip>
            {d.epic ? (
              <a href={`https://github.com/${d.epic.replace('#', '/issues/')}`} target="_blank" rel="noopener noreferrer">{shortRepo(d.epic.split('#')[0])} epic #{epicNo(d.epic)}</a>
            ) : (
              <a href={`https://github.com/${dispatchRepo(d)}`} target="_blank" rel="noopener noreferrer">{dispatchRepo(d)}</a>
            )}
            <span>{d.runner === 'herdr' ? 'in herdr tabs' : 'in background sessions'}</span>
          </p>
        </div>
        <div className="row wrap" style={{ gap: 6 }}>
          <Button aria-expanded={showSettings} onClick={() => setShowSettings(!showSettings)}><Icon n="sliders" />Settings</Button>
          {d.state === 'running' ? <Button onClick={() => state.mutate({ id: d.id, state: 'paused' }, { onSuccess: () => toast('Paused: no new issue starts') })}><Icon n="pause" />Pause</Button> : null}
          {d.state === 'paused' ? <Button variant="primary" shortcut="r" onClick={() => state.mutate({ id: d.id, state: 'running' })}><Icon n="play" />Resume</Button> : null}
          {live ? <Button variant="ghost" shortcut="x" onClick={() => void cancel()}>Cancel</Button> : null}
        </div>
      </div>

      <section className="dsp-summary" aria-label="Progress">
        <p className="dsp-sentence">{summary(c)}</p>
        <div className="meter" role="img" aria-label={`${c.closed} of ${c.total} done`}><span style={{ width: `${c.total ? (c.closed / c.total) * 100 : 0}%`, background: 'var(--ship)' }} /></div>
        <p className="faint">
          {d.state === 'done' || d.state === 'cancelled' ? `Took ${secs(d.totals.seconds)}` : `Running for ${secs(d.totals.seconds)}`}
          {d.runner === 'headless' && d.totals.cost > 0 ? `. Spent ${money(d.totals.cost)} so far` : ''}
          {`. Up to ${d.settings.max} at a time, grind ${d.settings.grind}, CI: ${d.settings.ci ?? 'wait'}, ${d.settings.auto_merge ? 'merges by itself' : 'you merge'}.`}
        </p>
      </section>
      <NeedsYou d={d} onPick={pick} selected={selection.selected} />

      {d.state === 'paused' ? <Banner tone="review" icon="pause">Paused. Issues already running carry on; no new one starts until you resume.</Banner> : null}
      {limited && live ? <Banner tone="away" icon="clock">A Claude account hit its usage limit. New issues wait, and paused ones resume after the reset.</Banner> : null}
      {showSettings ? (
        <section className="box" aria-label="Dispatch settings">
          <SettingsFields live noBranch={!d.epic} value={d.settings} onChange={(p) => save.mutate({ id: d.id, s: p }, { onSuccess: () => toast('Saved: applies from each issue’s next step') })} />
        </section>
      ) : null}
      {d.state === 'done' ? <EndPanel d={d} /> : null}

      <div className="row">
        <h2 className="grow" style={{ fontSize: 15 }}>Issues</h2>
        <div className="seg" role="radiogroup" aria-label="Issue view">
          <button type="button" role="radio" aria-checked={view === 'graph'} className={view === 'graph' ? 'on' : ''} onClick={() => setView('graph')}>Graph</button>
          <button type="button" role="radio" aria-checked={view === 'list'} className={view === 'list' ? 'on' : ''} onClick={() => setView('list')}>List</button>
        </div>
      </div>
      <div className={`dsp-split${lane ? ' has-lane' : ''}`}>
        <div style={{ minWidth: 0 }}>
          {d.lanes.length ? (
            view === 'graph' ? <LaneGraph lanes={d.lanes} picked={picked} onPick={pick} rowProps={selection.rowProps} /> : <LaneTable lanes={d.lanes} picked={picked} onPick={pick} rowProps={selection.rowProps} />
          ) : <EmptyState icon="layers" title="No issues to run">This epic had no open child issues when it started.</EmptyState>}
        </div>
        {lane ? <KeyScope level="panel" active><LanePanel key={lane.key} d={d} l={lane} onClose={() => pick(null)} /></KeyScope> : <Feed events={d.events ?? []} onPick={pick} />}
      </div>
      {lane ? <Feed events={d.events ?? []} onPick={pick} /> : null}
      <p className="faint" style={{ fontSize: 12 }}>Steer from a terminal too: <span className="mono">aiw dispatch show {d.id}</span></p>
    </div>
  );
}
