import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/endpoints';
import { keys, useDelivery, usePlanning } from '../api/hooks';
import { BoardStatus, isRateLimited } from '../board/BoardStatus';
import { IssueAction } from '../board/IssueAction';
import { IssueSignals } from '../board/IssueSignals';
import { needsYou, placeCards } from '../board/columns';
import '../board/board.css';
import { Button, Chip, EmptyState, Icon, LinkButton } from '../components';
import { joinFeatures, type FeatureIssue } from '../lib/features';
import { routes } from '../lib/routes';
import { BOARD_COLUMNS, issueStatus } from '../lib/vocab';
import { usePanel } from '../panels/PanelContext';
import { useRegisterShortcuts, type ShortcutRow } from '../shell/shortcuts';
import { useRepo } from '../shell/useRepo';

const SHORTCUTS: ShortcutRow[] = [
  { keys: 'J / K', label: 'Board: next / previous card in a column' },
  { keys: 'H / L', label: 'Board: previous / next column' },
  { keys: 'Enter', label: 'Board: open the focused issue' },
];

interface LaneData {
  key: string;
  title: string;
  epic: number | null;
  slug?: string;
  running: number;
  cards: FeatureIssue[];
}

function Card({ c, repo }: { c: FeatureIssue; repo: string }) {
  const panel = usePanel();
  const open = () => panel.open({ kind: 'issue', repo, n: c.n });
  return (
    <div
      className={`card${needsYou(c) ? ' you' : ''}`}
      tabIndex={0}
      data-card=""
      onClick={open}
      onKeyDown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) open(); }}
      aria-label={`Issue ${c.n}: ${c.title}${needsYou(c) ? ', needs you' : ''}`}
    >
      <div className="row"><span className="ref">#{c.n}</span><span className="grow" />{needsYou(c) ? <Chip tone="you">Needs you</Chip> : null}</div>
      <div className="t">{c.title}</div>
      <IssueSignals card={c} />
      <div><IssueAction card={c} repo={repo} /></div>
    </div>
  );
}

function Lane({ lane, repo, flat }: { lane: LaneData; repo: string; flat: boolean }) {
  const { link } = useRepo();
  const cols = placeCards(lane.cards);
  const merged = lane.cards.filter((c) => issueStatus(c) === 'merged').length;
  return (
    <section className="lane" aria-label={flat ? 'All issues' : lane.title}>
      {!flat ? (
        <div className="lane-h">
          {lane.slug ? <Link className="name" style={{ textDecoration: 'none', color: 'inherit' }} to={link(routes.feature(lane.slug))}>{lane.title}</Link> : <span className="name">{lane.title}</span>}
          <span className="muted" style={{ fontSize: 13 }}>{merged} of {lane.cards.length} merged</span>
          {lane.epic ? (
            <>
              <LinkButton sm to={link(routes.newDispatch(`${repo}#${lane.epic}`))} title="Run the epic's issues as parallel lanes"><Icon n="bolt" />Run epic</LinkButton>
              {lane.running ? <span className="cap">{lane.running} running</span> : null}
            </>
          ) : null}
        </div>
      ) : null}
      <div className="board-scroll">
        <div className="board">
          {BOARD_COLUMNS.map((col) => (
            <div key={col.id}>
              <div className="bcol-h" style={{ ['--c' as string]: col.color }}><i /><h3 style={{ font: 'inherit' }}>{col.label}</h3><span className="faint">{cols[col.id].length}</span></div>
              <div className="bcol" data-lane={lane.key} data-col={col.id} role="list" aria-label={col.label}>
                {cols[col.id].map((c) => <div key={c.n} role="listitem" style={{ display: 'contents' }}><Card c={c} repo={repo} /></div>)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/** j/k/h/l move focus between cards (FR-18). Works on the DOM so it is the same in every lane. */
function useBoardKeys() {
  useRegisterShortcuts(SHORTCUTS);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || !'jkhl'.includes(e.key) || e.key.length !== 1) return;
      const t = e.target as HTMLElement | null;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable)) return;
      if (document.querySelector('[role=dialog],[role=alertdialog],[role=menu]')) return;
      const cur = (document.activeElement as HTMLElement | null)?.closest<HTMLElement>('[data-card]');
      const first = document.querySelector<HTMLElement>('[data-card]');
      if (!cur) {
        if (first) { e.preventDefault(); first.focus(); }
        return;
      }
      e.preventDefault();
      const colEl = cur.closest<HTMLElement>('[data-col]')!;
      const cards = [...colEl.querySelectorAll<HTMLElement>('[data-card]')];
      const idx = cards.indexOf(cur);
      if (e.key === 'j' || e.key === 'k') {
        cards[idx + (e.key === 'j' ? 1 : -1)]?.focus();
        return;
      }
      const ids = BOARD_COLUMNS.map((c) => c.id);
      const step = e.key === 'l' ? 1 : -1;
      for (let k = ids.indexOf(colEl.dataset.col as (typeof ids)[number]) + step; k >= 0 && k < ids.length; k += step) {
        const list = [...document.querySelectorAll<HTMLElement>(`[data-lane="${colEl.dataset.lane}"][data-col="${ids[k]}"] [data-card]`)];
        if (list.length) { list[Math.min(idx, list.length - 1)].focus(); return; }
      }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);
}

export function BoardPage() {
  const { repo, current } = useRepo();
  const qc = useQueryClient();
  const del = useDelivery(repo);
  const plan = usePlanning(repo);
  const [flat, setFlat] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  useBoardKeys();

  const lanes = useMemo<LaneData[]>(() => {
    const feats = joinFeatures(plan.data?.prds ?? [], del.data?.lanes ?? []);
    return (del.data?.lanes ?? [])
      .map((l) => {
        const f = l.epic != null ? feats.find((x) => x.epic === l.epic) : undefined;
        return {
          key: String(l.epic ?? 'none'),
          title: l.title,
          epic: l.epic,
          slug: f?.slug,
          running: l.running,
          cards: l.cards.map((c) => ({ ...c, status: issueStatus(c) })),
        };
      })
      .filter((l) => l.cards.some((c) => c.status !== 'merged'));
  }, [plan.data, del.data]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      const d = await api.delivery(repo, true);
      qc.setQueryData(keys.delivery(repo), d);
      await qc.invalidateQueries({ queryKey: ['planning'] });
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="content-inner" style={{ maxWidth: 'none' }}>
      <div className="page-head">
        <div className="grow"><h1>Board</h1><p className="sub">Every open issue in {current?.name ?? repo}, by where it is in the build.</p></div>
        {del.data && !isRateLimited(del.data) ? <Button disabled={refreshing} onClick={refresh}><Icon n="refresh" />{refreshing ? 'Refreshing…' : 'Refresh'}</Button> : null}
        <div className="seg" role="group" aria-label="Group by">
          <button type="button" className={!flat ? 'on' : ''} aria-pressed={!flat} onClick={() => setFlat(false)}>By feature</button>
          <button type="button" className={flat ? 'on' : ''} aria-pressed={flat} onClick={() => setFlat(true)}>All issues</button>
        </div>
      </div>
      <BoardStatus meta={del.data} failed={del.isError && !!del.data} />
      {del.isError && !del.data ? (
        <EmptyState icon="alert" title="Board unavailable, retrying" actions={<Button onClick={() => del.refetch()}>Retry now</Button>}>{del.error.message}</EmptyState>
      ) : !del.data ? (
        <div className="board-scroll" aria-busy="true" aria-label="Loading the board">
          <div className="board-skel">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="stack">{[0, 1].map((j) => <div key={j} className="skel" />)}</div>)}</div>
        </div>
      ) : lanes.length === 0 ? (
        <EmptyState icon="board" title="Nothing to build yet" actions={<Link className="btn" to={routes.features + (repo ? `?repo=${repo}` : '')}>Go to features</Link>}>
          Issues land here once a PRD is approved and split into tasks.
        </EmptyState>
      ) : flat ? (
        <Lane lane={{ key: 'all', title: 'All issues', epic: null, running: 0, cards: lanes.flatMap((l) => l.cards) }} repo={repo} flat />
      ) : (
        lanes.map((l) => <Lane key={l.key} lane={l} repo={repo} flat={false} />)
      )}
    </div>
  );
}
