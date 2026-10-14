import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { poll } from './app.js';
import { openCleanup } from './cleanup.js';
import { addTokens, ago, grindLabel, loadPref, savePref, tokensText, tokensTitle } from './fmt.js';
import { GhChips, GhLinks, quiet } from './ghstatus.js';
import { RepoPicker, loadRepoList } from './repopicker.js';

const html = htm.bind(h);

// The meta row already shows #N, so a missing title says so instead of repeating the number.
export const titleKnown = (card) => !!card.title && !card.title.endsWith('(title unavailable)');
export function cardTitle(card) {
  return titleKnown(card) ? card.title : 'Title unavailable';
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

// A card needs you when its session waits on an answer, its run escalated, or its grind paused.
export function needsYou(card, columnKey, sessions) {
  const chips = cardChips(card, columnKey, matchSession(card, sessions));
  return chips.includes('waiting') || chips.includes('escalated') || (card.grind && card.grind.state === 'paused') || false;
}

// Where a card stands on each filter dimension. PR state is GitHub's; a PR whose state has not
// loaded yet is 'unknown', so it matches only "Any".
export function cardFacets(card, columnKey) {
  const pr = card.gh?.pr?.state ? card.gh.pr.state.toLowerCase() : card.pr ? 'unknown' : 'none';
  const g = card.grind?.state;
  return {
    run: columnKey === 'done' ? 'done' : 'active',
    pr,
    ci: pr === 'open' ? card.gh.pr.ci || 'none' : 'none',
    grind: !g ? 'none' : ['running', 'idle', 'queued'].includes(g) ? 'active' : g,
  };
}

// The board's filter dimensions: [key, label, [[value, label]]]; '' is "Any".
export const FACETS = [
  ['run', 'Status', [['active', 'In progress'], ['done', 'Done']]],
  ['pr', 'PR', [['none', 'No PR'], ['open', 'Open'], ['merged', 'Merged'], ['closed', 'Closed']]],
  ['ci', 'CI', [['green', 'Passing'], ['red', 'Failing'], ['pending', 'Running']]],
  ['grind', 'Grind', [['none', 'Not started'], ['active', 'Grinding'], ['paused', 'Paused'], ['done', 'Done']]],
];
export const NO_FILTERS = { repo: '', query: '', needs: false, run: '', pr: '', ci: '', grind: '' };
export const activeFacets = (f) => FACETS.filter(([k]) => f[k]).length + (f.needs ? 1 : 0);

// Each card with its facets and need-you flag, worked out once per render: the filter and every
// option count then only compare fields.
export function annotate(columns, sessions = []) {
  return columns.flatMap((c) => c.cards.map((card) => ({ card, col: c.key, at: cardFacets(card, c.key), needs: needsYou(card, c.key, sessions) })));
}

// f: { repo, query, needs, run, pr, ci, grind }. query matches #N, the title or the repo, case-insensitively.
export function entryMatches(e, f) {
  const k = e.card;
  const q = String(f.query || '').trim().toLowerCase().replace(/^#/, '');
  if (f.repo && k.owner + '/' + k.repo !== f.repo) return false;
  if (q && !(String(k.issue) === q || (k.owner + '/' + k.repo).toLowerCase().includes(q) || (titleKnown(k) && k.title.toLowerCase().includes(q)))) return false;
  if (f.needs && !e.needs) return false;
  return FACETS.every(([key]) => !f[key] || e.at[key] === f[key]);
}

export function filterColumns(columns, f = NO_FILTERS, sessions = [], entries = null) {
  if (!f.repo && !String(f.query || '').trim() && !f.needs && !FACETS.some(([k]) => f[k])) return columns;
  const keep = new Set((entries || annotate(columns, sessions)).filter((e) => entryMatches(e, f)).map((e) => e.card));
  return columns.map((c) => ({ ...c, cards: c.cards.filter((k) => keep.has(k)) }));
}

export const countCards = (columns) => columns.reduce((n, c) => n + c.cards.length, 0);

export function repoOptions(columns, selected) {
  const set = new Set(columns.flatMap((c) => c.cards.map((k) => k.owner + '/' + k.repo)));
  if (selected) set.add(selected);
  return [...set].sort();
}

// The filter's choices: registered repos (with their names and paths) plus any repo with cards.
export function filterRepos(columns, selected, registered = []) {
  const known = new Map(registered.map((r) => [r.slug, r]));
  const slugs = new Set([...repoOptions(columns, selected), ...known.keys()]);
  return [...slugs].sort().map((slug) => ({ value: slug, name: (known.get(slug) || {}).name || slug, path: (known.get(slug) || {}).path || '' }));
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
      if (needsYou(card, col.key, sessions)) waiting++;
    }
  }
  const day = now.toDateString();
  let today = 0;
  let todayTokens = null;
  for (const s of sessions || []) {
    if (!s || !s.started_at || new Date(s.started_at).toDateString() !== day) continue;
    if (typeof s.cost === 'number') today += s.cost;
    todayTokens = addTokens(todayTokens, s.tokens);
  }
  return { live, waiting, today, todayTokens };
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
    <span class="card-meta"><span>#${card.issue}</span><span class="card-repo" title=${card.owner + '/' + card.repo}>${card.repo}</span>${card.pipeline && html`<span class="card-pipe" title="Part of a dispatch pipeline">pipeline</span>`}${card.updated && html`<span class="card-age" title=${'Last update ' + new Date(card.updated * 1000).toLocaleString()}>${ago(card.updated)}</span>`}</span>
    <span class=${titleKnown(card) ? 'card-title' : 'card-title muted'}>${cardTitle(card)}</span>
    <span class="chips">
      ${cardChips(card, columnKey, session).filter((c, _, all) => !(c === 'done' && all.length === 1 && (card.grind || card.gh))).map((c) => html`<span class="chip chip-${c.replace(' ', '-')}">${c}</span>`)}
      ${card.grind && grindLabel(card.grind) && html`<span class=${'chip chip-grind-' + card.grind.state} title="Review grinding">${grindLabel(card.grind)}</span>`}
      <${GhChips} gh=${card.gh} />
      ${(cost || tokensText(session && session.tokens)) && html`<span class="cost" title=${tokensTitle(session && session.tokens)}>${[cost, tokensText(session && session.tokens)].filter(Boolean).join(' · ')}</span>`}
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

const FACET_KEY = 'aiw.boardFacets';
function loadFacets() {
  try {
    const saved = JSON.parse(loadPref(globalThis.localStorage, FACET_KEY) || '{}');
    return Object.fromEntries(FACETS.map(([k, , opts]) => [k, opts.some(([v]) => v === saved[k]) ? saved[k] : '']));
  } catch {
    return Object.fromEntries(FACETS.map(([k]) => [k, '']));
  }
}

export class Board extends Component {
  state = { data: null, repo: loadPref(globalThis.localStorage, 'aiw.boardRepo'), query: '', needs: false, ...loadFacets(), error: false, doneOpen: false, panel: false };

  // Set one filter (and remember the facet ones); passing NO_FILTERS clears them all.
  setFilter = (patch) => {
    this.setState(patch, () => {
      if ('repo' in patch) savePref(globalThis.localStorage, 'aiw.boardRepo', this.state.repo);
      savePref(globalThis.localStorage, FACET_KEY, JSON.stringify(Object.fromEntries(FACETS.map(([k]) => [k, this.state[k]]))));
    });
  };

  componentDidMount() {
    loadRepoList(true).then((registered) => this.setState({ registered })); // without it the filter lists repos with cards
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
    this.before = this.boardEl ? cardRects(this.boardEl) : null; // a ref: preact 11 has no this.base
  }

  componentDidUpdate() {
    if (!this.before || !this.boardEl || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const after = cardRects(this.boardEl);
    for (const [key, dx, dy] of flipDeltas(this.before, after)) {
      after.get(key).el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration: 320, easing: 'cubic-bezier(0.2, 0.7, 0.2, 1)' });
    }
    this.before = null;
  }

  render({ sessions }, { data, repo, error, doneOpen, panel }) {
    if (!data) {
      return error
        ? html`<h1>Board</h1><p role="status">Board unavailable, retrying…</p>`
        : html`<h1 class="sr-only">Board</h1><${Skeleton} />`;
    }
    const f = { ...NO_FILTERS, ...Object.fromEntries(Object.keys(NO_FILTERS).map((k) => [k, this.state[k] ?? NO_FILTERS[k]])) };
    const sum = boardSummary(data.columns, sessions); // every repo: a remembered filter must not hide work waiting elsewhere
    const entries = annotate(data.columns, sessions);
    const columns = filterColumns(data.columns, f, sessions, entries);
    const filtering = !!(f.repo || f.query.trim() || activeFacets(f));
    const total = countCards(data.columns);
    const shownN = countCards(columns);
    const nFacets = FACETS.filter(([k]) => f[k]).length;
    // An option's count: the cards it would leave, given every other filter.
    const countFor = (key, value) => entries.filter((e) => entryMatches(e, { ...f, [key]: value })).length;
    return html`
      <h1 class="sr-only">Board</h1>
      <div class="strip">
        <span title="Across all repos, whatever the filters"><b>${sum.live}</b> live</span>
        <button type="button" class=${'strip-wait' + (f.needs ? ' on' : '')} aria-pressed=${f.needs ? 'true' : 'false'} disabled=${!sum.waiting && !f.needs}
          title="Runs waiting on an answer, escalated, or with a paused grind. Click to show only these." onClick=${() => this.setState({ needs: !f.needs })}><b>${sum.waiting}</b> need you</button>
        <span title=${`Across all repos${sum.todayTokens ? ` · ${tokensTitle(sum.todayTokens)}` : ''}`}><b>$${sum.today.toFixed(2)}</b>${sum.todayTokens && html` · <b>${tokensText(sum.todayTokens)}</b>`} today</span>
        <span class="spacer"></span>
        <input type="search" data-search class="strip-search" aria-label="Filter cards" placeholder="Search: #12, title or repo" value=${f.query}
          onInput=${(e) => this.setState({ query: e.target.value })} onKeyDown=${(e) => { if (e.key === 'Escape') this.setState({ query: '' }); }} />
        <div class="strip-filter"><label for="board-repo">Repo</label>
          <${RepoPicker} id="board-repo" allLabel="All repos" repos=${filterRepos(data.columns, repo, this.state.registered)} value=${{ repo, path: '' }}
            onPick=${(sel) => this.setFilter({ repo: sel.repo })} />
        </div>
        <button type="button" class=${'btn strip-filters' + (nFacets ? ' on' : '')} aria-expanded=${panel ? 'true' : 'false'} aria-controls="board-filters"
          onClick=${() => this.setState({ panel: !panel })}>Filters${nFacets > 0 && html` <span class="count">${nFacets}</span>`}</button>
        <button type="button" class="btn" onClick=${() => openCleanup()}>Clean up…</button>
      </div>
      ${panel && html`<div id="board-filters" class="facets" role="group" aria-label="Filters">
        ${FACETS.map(([key, label, opts]) => html`<div class="facet" role="radiogroup" aria-label=${label}>
          <span class="facet-name">${label}</span>
          <div class="seg">
            ${[['', 'Any'], ...opts].map(([v, l]) => html`<button type="button" role="radio" aria-checked=${f[key] === v} class=${f[key] === v ? 'on' : ''}
              onClick=${() => this.setFilter({ [key]: v })}>${l}${v && html` <span class="muted">${countFor(key, v)}</span>`}</button>`)}
          </div>
        </div>`)}
      </div>`}
      ${filtering && html`<div class="active-filters" aria-live="polite">
        <span class="muted">Showing ${shownN} of ${total}</span>
        ${f.repo && html`<button type="button" class="fchip" onClick=${() => this.setFilter({ repo: '' })} aria-label=${`Remove repo filter ${f.repo}`}>Repo: ${f.repo.split('/').pop()} ×</button>`}
        ${f.query.trim() && html`<button type="button" class="fchip" onClick=${() => this.setState({ query: '' })} aria-label="Clear search">“${f.query.trim()}” ×</button>`}
        ${f.needs && html`<button type="button" class="fchip" onClick=${() => this.setState({ needs: false })}>Needs you ×</button>`}
        ${FACETS.filter(([k]) => f[k]).map(([k, label, opts]) => html`<button type="button" class="fchip" onClick=${() => this.setFilter({ [k]: '' })}
          aria-label=${`Remove ${label} filter`}>${label}: ${opts.find(([v]) => v === f[k])[1]} ×</button>`)}
        <button type="button" class="linkish" onClick=${() => this.setFilter({ ...NO_FILTERS })}>Clear all</button>
      </div>`}
      ${columns.every((c) => !c.cards.length) && (filtering
        ? html`<p class="board-empty">No cards match these filters. <button type="button" class="linkish" onClick=${() => this.setFilter({ ...NO_FILTERS })}>Clear all</button></p>`
        : html`<p class="board-empty">No runs yet. Start one from <a href="#/new">New run</a> or <a href="#/dispatch">Dispatch</a>.</p>`)}
      <div class="board" ref=${(el) => { this.boardEl = el; }}>
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
