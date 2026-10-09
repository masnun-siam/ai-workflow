import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { poll } from './app.js';
import { openCleanup } from './cleanup.js';
import { grindLabel } from './fmt.js';
import { GhChips, GhLinks, quiet } from './ghstatus.js';

const html = htm.bind(h);

export function cardTitle(card) {
  return card.title ? card.title : '#' + card.issue;
}

export function runHref(card) {
  return `#/run/${encodeURIComponent(card.owner)}/${encodeURIComponent(card.repo)}/${card.issue}`;
}

export function matchSession(card, sessions) {
  return (
    (sessions || []).find(
      (s) =>
        s &&
        s.link &&
        typeof s.link === 'object' &&
        s.link.owner === card.owner &&
        s.link.repo === card.repo &&
        Number(s.link.issue) === Number(card.issue),
    ) || null
  );
}

export function cardChips(card, columnKey, session) {
  // The Ledger is done once the PR is handed back for review; only GitHub knows it merged.
  if (columnKey === 'done') return [card.gh?.pr?.state === 'MERGED' ? 'merged' : 'done'];
  const chips = [];
  const status = session && (session.status ?? session.outcome);
  if (status === 'running' || status === 'stopped' || status === 'limited') chips.push(status);
  else if (status === 'waiting' || (session && session.waiting === true)) chips.push('waiting');
  else if (card.escalated) chips.push('escalated');
  if (session && session.resumed_fresh === true) chips.push('resumed fresh');
  return chips;
}

export function formatCost(cost) {
  return typeof cost === 'number' && Number.isFinite(cost) ? '$' + cost.toFixed(2) : '';
}

export function filterColumns(columns, repo) {
  if (!repo) return columns;
  return columns.map((c) => ({ ...c, cards: c.cards.filter((k) => k.owner + '/' + k.repo === repo) }));
}

export function repoOptions(columns, selected) {
  const set = new Set(columns.flatMap((c) => c.cards.map((k) => k.owner + '/' + k.repo)));
  if (selected) set.add(selected);
  return [...set].sort();
}

export const STATION_LABELS = {
  researcher: 'Research', planner: 'Plan', sdet: 'SDET', dev: 'Dev',
  verifier: 'Verify', reviewer: 'Review', fixer: 'Fix', done: 'Done',
};
export const stationLabel = (key) => STATION_LABELS[key] || key;

export const DONE_LIMIT = 10;
export function visibleCards(col, expanded) {
  return col.key === 'done' && !expanded ? col.cards.slice(0, DONE_LIMIT) : col.cards;
}

export function boardSummary(columns, sessions, now = new Date()) {
  let live = 0;
  let waiting = 0;
  for (const col of columns) {
    for (const card of col.cards) {
      const chips = cardChips(card, col.key, matchSession(card, sessions));
      if (chips.includes('running')) live++;
      if (chips.includes('waiting') || chips.includes('escalated') || (card.grind && card.grind.state === 'paused')) waiting++;
    }
  }
  const day = now.toDateString();
  let today = 0;
  for (const s of sessions || []) {
    if (s && typeof s.cost === 'number' && s.started_at && new Date(s.started_at).toDateString() === day) today += s.cost;
  }
  return { live, waiting, today };
}

// FLIP: cards whose position changed between two polls, as [key, dx, dy] to animate from.
export function flipDeltas(before, after) {
  const moved = [];
  for (const [key, from] of before) {
    const to = after.get(key);
    if (to && (Math.abs(from.x - to.x) > 1 || Math.abs(from.y - to.y) > 1)) moved.push([key, from.x - to.x, from.y - to.y]);
  }
  return moved;
}

const cardRects = (root) => {
  const rects = new Map();
  for (const el of root.querySelectorAll('[data-card]')) {
    const r = el.getBoundingClientRect();
    rects.set(el.dataset.card, { x: r.left, y: r.top, el });
  }
  return rects;
};

export function boardChanged(prevText, nextData) {
  return JSON.stringify(nextData) !== prevText;
}

function Card({ card, columnKey, sessions }) {
  const session = matchSession(card, sessions);
  const cost = formatCost(session && session.cost);
  const key = card.owner + '/' + card.repo + '#' + card.issue;
  const state = session && (session.status ?? session.outcome);
  const cleanable = columnKey === 'done' || state === 'stopped' || state === 'failed' || (!session && quiet(card.updated, card.escalated ? 'escalated' : 'running')) || card.gh?.pr?.state === 'MERGED';
  return html`<div class="card-wrap">${cleanable && html`<button type="button" class="card-clean" aria-label=${'Clean up ' + key} title="Clean up" onClick=${() => openCleanup(key)}>Clean up</button>`}
  <a class="card" href=${runHref(card)} data-card=${key}>
    <span class="card-meta"><span>#${card.issue}</span><span class="card-repo" title=${card.owner + '/' + card.repo}>${card.repo}</span>${card.pipeline && html`<span class="card-pipe" title="Part of a dispatch pipeline">pipeline</span>`}</span>
    <span class="card-title">${cardTitle(card)}</span>
    <span class="chips">
      ${cardChips(card, columnKey, session).filter((c, _, all) => !(c === 'done' && all.length === 1 && (card.grind || card.gh))).map((c) => html`<span class="chip chip-${c.replace(' ', '-')}">${c}</span>`)}
      ${card.grind && grindLabel(card.grind) && html`<span class=${'chip chip-grind-' + card.grind.state} title="Review grinding">${grindLabel(card.grind)}</span>`}
      <${GhChips} gh=${card.gh} />
      ${cost && html`<span class="cost">${cost}</span>`}
    </span>
    ${card.note && html`<span class="card-note">${card.note}</span>`}
  </a>
  <${GhLinks} owner=${card.owner} repo=${card.repo} issue=${card.issue} pr=${card.pr} gh=${card.gh} /></div>`;
}

function Skeleton() {
  return html`<div class="board" aria-busy="true" aria-label="Loading board">
    ${Object.keys(STATION_LABELS).map(
      (key) => html`<section class="column"><h2>${stationLabel(key)}</h2>
        ${key === 'done' || key === 'sdet' || key === 'verifier' ? null : html`<div class="card skeleton"></div><div class="card skeleton"></div>`}
      </section>`,
    )}
  </div>`;
}

export class Board extends Component {
  state = { data: null, repo: '', error: false, doneOpen: false };

  componentDidMount() {
    this.stop = poll('/board.json', 3000, (r) => {
      if (!r.ok) {
        if (!this.state.data) this.setState({ error: true }); // keep last data on later failures
        return;
      }
      if (!boardChanged(this.last, r.data)) return;
      this.last = JSON.stringify(r.data);
      this.setState({ data: r.data, error: false });
    });
  }

  componentWillUnmount() {
    if (this.stop) this.stop();
  }

  componentWillUpdate() {
    this.before = this.base && this.base.querySelectorAll ? cardRects(this.base) : null;
  }

  componentDidUpdate() {
    if (!this.before || !this.base || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const after = cardRects(this.base);
    for (const [key, dx, dy] of flipDeltas(this.before, after)) {
      after.get(key).el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration: 320, easing: 'cubic-bezier(0.2, 0.7, 0.2, 1)' });
    }
    this.before = null;
  }

  render({ sessions }, { data, repo, error, doneOpen }) {
    if (!data) {
      return error
        ? html`<h1>Board</h1><p role="status">Board unavailable, retrying…</p>`
        : html`<h1 class="sr-only">Board</h1><${Skeleton} />`;
    }
    const columns = filterColumns(data.columns, repo);
    const sum = boardSummary(columns, sessions);
    return html`
      <h1 class="sr-only">Board</h1>
      <div class="strip">
        <span><b>${sum.live}</b> live</span>
        <span class="strip-wait"><b>${sum.waiting}</b> waiting</span>
        <span><b>$${sum.today.toFixed(2)}</b> today</span>
        <span class="spacer"></span>
        <button type="button" class="btn" onClick=${() => openCleanup()}>Clean up…</button>
        <label class="strip-filter">Repo
          <select data-search value=${repo} onChange=${(e) => this.setState({ repo: e.target.value })}>
            <option value="">All repos</option>
            ${repoOptions(data.columns, repo).map((r) => html`<option value=${r}>${r}</option>`)}
          </select>
        </label>
      </div>
      ${columns.every((c) => !c.cards.length) && html`<p class="board-empty">No runs${repo ? ' for this repo' : ''} yet. Start one from <a href="#/new">New run</a> or <a href="#/dispatch">Dispatch</a>.</p>`}
      <div class="board">
        ${columns.map((col) => {
          const shown = visibleCards(col, doneOpen);
          const hidden = col.cards.length - shown.length;
          // Empty stations shrink to a narrow rail so the busy ones get the width.
          return html`<section class=${col.cards.length ? 'column' : 'column is-empty'} aria-label=${stationLabel(col.key)}>
            <h2><span>${stationLabel(col.key)}</span><span class="mono">${col.cards.length}</span></h2>
            ${shown.length
              ? shown.map((card) => html`<${Card} key=${card.owner + '/' + card.repo + '#' + card.issue} card=${card} columnKey=${col.key} sessions=${sessions} />`)
              : html`<p class="empty">No runs</p>`}
            ${col.key === 'done' && col.cards.length > DONE_LIMIT && html`<button type="button" class="btn" onClick=${() => this.setState({ doneOpen: !doneOpen })}>
              ${doneOpen ? 'Show fewer' : `Show all ${col.cards.length} (${hidden} more)`}
            </button>`}
          </section>`;
        })}
      </div>`;
  }
}
