// One dispatch: live settings, totals, lanes as a graph or a table, the picked lane, the activity feed, end actions.
import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useDispatch, useDispatchSeen, useDispatchSettings, useDispatchState, useEndAction, useSessions } from '../api/hooks';
import type { Dispatch, DispatchEvent, EndAction } from '../api/types';
import { Banner, Button, Chip, EmptyState, Icon, useConfirm, useToast } from '../components';
import { clockText, fmtTokens, money, shortRepo } from '../lib/format';
import { routes } from '../lib/routes';
import { LanePanel } from '../dispatch/LanePanel';
import { LaneGraph, LaneTable } from '../dispatch/LaneViews';
import { SettingsFields } from '../dispatch/SettingsFields';
import { DSTATE, counts, epicNo, issueNo, secs } from '../dispatch/vocab';
import '../dispatch/dispatch.css';

const VIEW_KEY = 'aiw.dispatch.view';
const readView = () => {
  try {
    return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'graph';
  } catch {
    return 'graph';
  }
};

const KIND_ICON: Record<string, string> = { needs_you: '!', held: '■', awaiting_merge: '↗', merged: '✓', finished: '★', stage: '→', end: '◆' };

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
              {e.lane ? <button type="button" className="linkish mono" onClick={() => onPick(e.lane!)}>{issueNo(e.lane)}</button> : null}
              <span>{e.text}</span>
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
  const prs = Object.entries(d.final_prs ?? {});
  const go = (action: EndAction, msg: string) => end.mutate({ id: d.id, action }, { onSuccess: () => toast(msg) });
  return (
    <section className="dsp-end" aria-label="What next">
      <div className="row"><Icon n="check" /><h2 className="grow" style={{ fontSize: 15 }}>Every lane is done. What next?</h2></div>
      <p className="muted">Nothing below runs by itself. QA files any bug it finds as a new issue of the epic, and new issues join this dispatch as lanes.</p>
      <div className="row wrap" style={{ gap: 8 }}>
        {fb && !prs.length ? <Button variant="primary" onClick={() => go('open-pr', 'Opening the PR')}><Icon n="pr" />Open PR from {fb}</Button> : null}
        <Button onClick={() => go('qa', 'QA session starting')}><Icon n="eye" />Run QA{fb ? ` on ${fb}` : ''}</Button>
        {prs.length ? <Button onClick={() => go('grind-pr', 'Grind starting')}><Icon n="refresh" />Grind the final PR</Button> : null}
      </div>
      {prs.length ? (
        <ul className="stack" style={{ gap: 4, margin: 0, paddingLeft: 18 }}>
          {prs.map(([repo, url]) => <li key={repo}><a href={url} target="_blank" rel="noopener noreferrer">{shortRepo(repo)}: {url.replace(/^.*\/pull\//, 'PR #')}</a></li>)}
        </ul>
      ) : null}
    </section>
  );
}

function Stat({ k, v, tone }: { k: string; v: string | number; tone?: string }) {
  return <div className="dsp-stat"><span className="faint">{k}</span><b className={tone ? `dsp-c t-${tone}` : ''}>{v}</b></div>;
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
    if (await confirm({ title: 'Cancel this dispatch?', body: 'No new lanes start and nothing is merged. Lanes already running keep their sessions and PRs; close them yourself.', okLabel: 'Cancel dispatch', cancelLabel: 'Keep it', danger: true }))
      state.mutate({ id: d.id, state: 'cancelled' }, { onSuccess: () => toast('Dispatch cancelled') });
  };

  return (
    <div className="content-inner dsp-page">
      <nav className="crumbs" aria-label="Breadcrumb">
        <Link to={routes.dispatches} style={{ textDecoration: 'none' }}>Dispatches</Link><Icon n="right" s={13} /><span>Epic #{epicNo(d.epic)}</span>
      </nav>
      <div className="page-head">
        <div className="grow" style={{ minWidth: 0 }}>
          <h1 className="ellipsis">{d.title || `Epic #${epicNo(d.epic)}`}</h1>
          <p className="sub row wrap" style={{ gap: 10 }}>
            <Chip tone={st.tone} live={st.live}>{st.label}</Chip>
            <a href={`https://github.com/${d.epic.replace('#', '/issues/')}`} target="_blank" rel="noopener noreferrer" className="mono">{d.epic}</a>
            <span>{d.runner === 'herdr' ? 'herdr tabs' : 'headless sessions'}</span>
            <span>started {clockText(d.created_at)}</span>
          </p>
        </div>
        <div className="row wrap" style={{ gap: 6 }}>
          <Button aria-expanded={showSettings} onClick={() => setShowSettings(!showSettings)}><Icon n="sliders" />Settings</Button>
          {d.state === 'running' ? <Button onClick={() => state.mutate({ id: d.id, state: 'paused' }, { onSuccess: () => toast('Paused: no new lanes start') })}><Icon n="pause" />Pause</Button> : null}
          {d.state === 'paused' ? <Button variant="primary" onClick={() => state.mutate({ id: d.id, state: 'running' })}><Icon n="play" />Resume</Button> : null}
          {live ? <Button variant="ghost" onClick={() => void cancel()}>Cancel</Button> : null}
        </div>
      </div>

      <div className="dsp-stats" aria-label="Totals">
        <div className="dsp-stat grow">
          <span className="faint">{c.closed} of {c.total} done</span>
          <div className="meter" role="img" aria-label={`${c.closed} of ${c.total} lanes done`}><span style={{ width: `${c.total ? (c.closed / c.total) * 100 : 0}%`, background: 'var(--ship)' }} /></div>
        </div>
        <Stat k="Running" v={`${c.active} / ${d.settings.max}`} />
        <Stat k="Queued" v={c.queued} />
        <Stat k="Need you" v={c.you} tone={c.you ? 'you' : undefined} />
        <Stat k="Elapsed" v={secs(d.totals.seconds)} />
        <Stat k="Cost" v={d.runner === 'herdr' ? '—' : money(d.totals.cost)} />
        <Stat k="Tokens" v={d.runner === 'herdr' ? '—' : fmtTokens(d.totals.tokens)} />
      </div>

      {d.state === 'paused' ? <Banner tone="review" icon="pause">Paused: running lanes carry on, no new lane starts.</Banner> : null}
      {limited && live ? <Banner tone="away" icon="clock">A Claude account is at its usage limit: new lanes wait and limited ones resume after the reset.</Banner> : null}
      {showSettings ? (
        <section className="box" aria-label="Dispatch settings">
          <SettingsFields live value={d.settings} onChange={(p) => save.mutate({ id: d.id, s: p }, { onSuccess: () => toast('Saved: applies at each lane’s next step') })} />
        </section>
      ) : null}
      {d.state === 'done' ? <EndPanel d={d} /> : null}

      <div className="row">
        <h2 className="grow" style={{ fontSize: 15 }}>Lanes</h2>
        <div className="seg" role="radiogroup" aria-label="Lane view">
          <button type="button" role="radio" aria-checked={view === 'graph'} className={view === 'graph' ? 'on' : ''} onClick={() => setView('graph')}>Graph</button>
          <button type="button" role="radio" aria-checked={view === 'list'} className={view === 'list' ? 'on' : ''} onClick={() => setView('list')}>List</button>
        </div>
      </div>
      <div className={`dsp-split${lane ? ' has-lane' : ''}`}>
        <div style={{ minWidth: 0 }}>
          {d.lanes.length ? (
            view === 'graph' ? <LaneGraph lanes={d.lanes} picked={picked} onPick={pick} /> : <LaneTable lanes={d.lanes} picked={picked} onPick={pick} />
          ) : <EmptyState icon="layers" title="No lanes">This epic had no open child issues.</EmptyState>}
        </div>
        {lane ? <LanePanel key={lane.key} d={d} l={lane} onClose={() => pick(null)} /> : <Feed events={d.events ?? []} onPick={pick} />}
      </div>
      {lane ? <Feed events={d.events ?? []} onPick={pick} /> : null}
      <p className="faint" style={{ fontSize: 12 }}>Steer from a terminal too: <span className="mono">aiw dispatch show {d.id}</span></p>
    </div>
  );
}
