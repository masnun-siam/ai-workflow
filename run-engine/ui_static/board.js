import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { poll } from './app.js';

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
  if (columnKey === 'done') return ['merged'];
  const chips = [];
  const status = session && session.status;
  if (status === 'running' || status === 'stopped') chips.push(status);
  else if (status === 'waiting' || (!session && card.escalated)) chips.push('waiting');
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

export function boardChanged(prevText, nextData) {
  return JSON.stringify(nextData) !== prevText;
}

function Card({ card, columnKey, sessions }) {
  const session = matchSession(card, sessions);
  const cost = formatCost(session && session.cost);
  return html`<a class="card" href=${runHref(card)}>
    <span class="card-meta">${card.owner}/${card.repo} #${card.issue}</span>
    <span class="card-title">${cardTitle(card)}</span>
    <span class="chips">
      ${cardChips(card, columnKey, session).map((c) => html`<span class="chip chip-${c.replace(' ', '-')}">${c}</span>`)}
      ${cost && html`<span class="cost">${cost}</span>`}
    </span>
  </a>`;
}

export class Board extends Component {
  state = { data: null, repo: '' };

  componentDidMount() {
    this.stop = poll('/board.json', 3000, (r) => {
      if (!r.ok) return; // keep last data on failure
      if (!boardChanged(this.last, r.data)) return;
      this.last = JSON.stringify(r.data);
      this.setState({ data: r.data });
    });
  }

  componentWillUnmount() {
    if (this.stop) this.stop();
  }

  render({ sessions }, { data, repo }) {
    if (!data) return html`<h1>Board</h1><p>Loading board…</p>`;
    const columns = filterColumns(data.columns, repo);
    return html`
      <h1>Board</h1>
      <label>Repo
        <select value=${repo} onChange=${(e) => this.setState({ repo: e.target.value })}>
          <option value="">All repos</option>
          ${repoOptions(data.columns, repo).map((r) => html`<option value=${r}>${r}</option>`)}
        </select>
      </label>
      <div class="board">
        ${columns.map(
          (col) => html`<section class="column" aria-label=${col.key}>
            <h2>${col.key} (${col.cards.length})</h2>
            ${col.cards.length
              ? col.cards.map((card) => html`<${Card} card=${card} columnKey=${col.key} sessions=${sessions} />`)
              : html`<p class="empty">No runs</p>`}
          </section>`,
        )}
      </div>`;
  }
}
