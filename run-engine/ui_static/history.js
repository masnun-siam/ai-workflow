import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';

import { formatWhen, shortRepo, sessionLabel, tokensText, tokensTitle, currentRepo, setRepo, sendJson } from './fmt.js';
import { toast } from './toast.js';
import { openCleanup } from './cleanup.js';
import { RepoPicker, loadRepoList } from './repopicker.js';
import { canStop, stopSession, canRerun, rerun, rerunBody } from './session.js';

export { canRerun, rerunBody };

const html = htm.bind(h);

const DASH = '—';
const OUTCOMES = ['queued', 'starting', 'running', 'waiting', 'limited', 'done', 'failed', 'stopped'];

export function rowOutcome(s) {
  return s.outcome === 'waiting' || s.waiting === true ? 'waiting' : s.outcome;
}

export function transcriptHref(s) {
  return sessionHref(s);
}

export function sessionHref(s) {
  return `#/session/${encodeURIComponent(s.id)}`;
}

export function rowAction(s) {
  switch (rowOutcome(s)) {
    case 'failed':
      return { kind: 'terminal', label: 'Continue in terminal', command: s.resume_command };
    case 'waiting':
      return { kind: 'link', label: 'Answer', href: '#/answer/' + encodeURIComponent(s.id) };
    case 'limited':
      return { kind: 'post', label: 'Resume now', method: 'POST', url: `/api/sessions/${encodeURIComponent(s.id)}/resume` };
    case 'stopped':
      return { kind: 'post', label: 'Resume', method: 'POST', url: `/api/sessions/${encodeURIComponent(s.id)}/resume` };
    default: // the row itself opens the session
      return null;
  }
}

export const PAGE = 50;

// `owner/repo#n` for a session's link (a GitHub issue/PR URL or an {owner, repo, issue} object), else null.
// Issues and PRs share one number space, so a URL and an object for the same number are one item.
export function linkKey(link) {
  if (typeof link === 'string') {
    const m = /^https?:\/\/(?:www\.)?github\.com\/([^/\s]+)\/([^/\s]+)\/(?:issues|pull)\/(\d+)(?:[/?#]|$)/.exec(link);
    return m ? `${m[1]}/${m[2]}#${Number(m[3])}` : null;
  }
  if (link && typeof link === 'object' && link.owner && link.repo && Number.isInteger(link.issue) && link.issue > 0) return `${link.owner}/${link.repo}#${link.issue}`;
  return null;
}

// Outcome, repo (a checkout path) and a text search over the command, its link and its `owner/repo#n` key.
export function filterSessions(list, filter, { path = '', q = '' } = {}) {
  const needle = q.trim().toLowerCase();
  return list.filter((s) => (filter === 'all' || rowOutcome(s) === filter)
    && (!path || (s.repo_path || s.repo) === path)
    && (!needle || `${s.command || ''} ${typeof s.link === 'string' ? s.link : ''} ${linkKey(s.link) || ''}`.toLowerCase().includes(needle)));
}

// Cost of today, the last 7 days and the given list (the rows on screen). `now` in ms.
export function costTotals(all, shown, now = Date.now()) {
  const day = new Date(now); day.setHours(0, 0, 0, 0);
  const sum = (xs) => xs.reduce((t, s) => t + (typeof s.cost === 'number' ? s.cost : 0), 0);
  const since = (ms) => all.filter((s) => s.started_at && new Date(s.started_at).getTime() >= ms);
  return { today: sum(since(day.getTime())), week: sum(since(now - 7 * 86400000)), shown: sum(shown) };
}

// Oldest-first comparator on started_at; `dir` -1 flips it. Undated ones sort last either way.
const startMs = (s) => { const t = Date.parse(s.started_at); return Number.isNaN(t) ? null : t; };
const byStart = (dir) => (a, b) => { const x = startMs(a), y = startMs(b); return x === y ? 0 : x === null ? 1 : y === null ? -1 : (x - y) * dir; };

// The pinned section: waiting (oldest first) and queued/limited (newest first), from the whole unfiltered list.
export function pinnedSessions(list) {
  const waiting = list.filter((s) => rowOutcome(s) === 'waiting').sort(byStart(1));
  const queued = list.filter((s) => ['queued', 'limited'].includes(rowOutcome(s))).sort(byStart(-1));
  return { waiting, queued };
}

// Sessions grouped by the issue or PR they worked on (linkKey), newest group first, then one Other group for the unlinked.
export function groupSessions(list) {
  const by = new Map();
  const other = { key: 'other', link: null, other: true, items: [] };
  for (const s of list) {
    const k = linkKey(s.link);
    if (!k) { other.items.push(s); continue; }
    if (!by.has(k)) by.set(k, { key: k, link: k, items: [] });
    by.get(k).items.push(s);
  }
  const latest = (g) => g.items.reduce((m, s) => Math.max(m, startMs(s) ?? -Infinity), -Infinity);
  const groups = [...by.values()].sort((a, b) => latest(b) - latest(a) || 0);
  return other.items.length ? [...groups, other] : groups;
}

// One page of rows: groups until `limit` rows show (an issue/PR group is never split; Other and flat rows are).
export function pageRows(list, grouped, limit) {
  if (!grouped) return { groups: [{ key: 'flat', link: null, flat: true, items: list.slice(0, limit), total: list.length }], shown: Math.min(limit, list.length) };
  const groups = [];
  let shown = 0;
  for (const g of groupSessions(list)) {
    if (shown >= limit) break;
    const items = g.link ? g.items : g.items.slice(0, limit - shown);
    groups.push({ ...g, items, total: g.items.length });
    shown += items.length;
  }
  return { groups, shown };
}

// A click on the row opens the session, unless it is on a control, a modified click, or ends a text selection.
export function rowClickOpens(e, selected = '') {
  if (e.button > 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || selected) return false;
  return !(e.target && e.target.closest && e.target.closest('a, button, input, select, summary, details, label'));
}

const ghUrl = (key) => { const [slug, n] = key.split('#'); return `https://github.com/${slug}/issues/${n}`; };

export async function resumeSession(id) {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(id)}/resume`, { method: 'POST' });
    if (res.ok) return { ok: true };
    let error = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body && typeof body.error === 'string' && body.error) error = body.error;
    } catch {
      // body is not JSON: keep the status text
    }
    return { ok: false, error };
  } catch (e) {
    return { ok: false, error: (e && e.message) || 'Network error' };
  }
}

export function fmtCost(c) {
  return typeof c === 'number' && Number.isFinite(c) ? '$' + c.toFixed(2) : DASH;
}

export function fmtTime(iso) {
  if (!iso) return DASH;
  return Number.isNaN(new Date(iso).getTime()) ? String(iso) : formatWhen(iso);
}

// Grind commands are long instruction text; the short label plus the issue says more.
// A linked session reads `<command> · #n`, e.g. `pr-grind · #832`.
export function cmdLabel(s) {
  const label = sessionLabel(s.command);
  const k = linkKey(s.link);
  if (!k) return label;
  const name = label === 'pr-grind round' ? 'pr-grind' : label !== s.command ? label
    : /^\//.test(label) ? label.slice(1).split(/\s/)[0].replace(/^[\w-]+:/, '') : label.length > 40 ? `${label.slice(0, 40)}…` : label;
  return `${name} · #${k.split('#')[1]}`;
}


export class History extends Component {
  state = { filter: 'all', busy: {}, errors: {}, repo: currentRepo(), repos: [], q: '', limit: PAGE, grouped: true };

  componentDidMount() {
    loadRepoList().then((list) => !this.gone && this.setState({ repos: list.map((r) => ({ value: r.slug, name: r.name || r.slug, path: r.path || '' })) }));
  }

  componentWillUnmount() {
    this.gone = true;
  }

  // A repo pick is shared with the boards; "All repos" only clears this page's filter.
  pickRepo = ({ repo }) => {
    if (repo) setRepo(repo);
    this.setState({ repo: repo || '', limit: PAGE });
  };

  stop = async (s) => {
    const r = await stopSession(s.id);
    if (r.cancelled) return;
    this.setState((st) => ({ errors: { ...st.errors, [s.id]: r.ok ? null : r.error } }));
    if (r.ok) toast('Session stopped');
  };

  again = async (s) => {
    this.setState((st) => ({ busy: { ...st.busy, [s.id]: true } }));
    const r = await rerun(s);
    this.setState((st) => ({ busy: { ...st.busy, [s.id]: false }, errors: { ...st.errors, [s.id]: r.ok ? null : r.error } }));
    if (r.ok) { toast('Started again'); location.hash = `#/session/${encodeURIComponent(r.id)}`; }
  };

  // setState is async in preact, so a same-tick double click needs its own guard.
  inflight = new Set();

  resume = async (id) => {
    if (this.inflight.has(id)) return;
    this.inflight.add(id);
    this.setState((st) => ({ busy: { ...st.busy, [id]: true }, errors: { ...st.errors, [id]: null } }));
    const r = await resumeSession(id);
    this.inflight.delete(id);
    this.setState((st) => ({ busy: { ...st.busy, [id]: false }, errors: { ...st.errors, [id]: r.ok ? null : r.error } }));
    if (r.ok) toast('Session resumed');
  };

  action(s) {
    return html`<div class="row-acts">${this.primary(s)}
      ${canStop(s) && html`<button type="button" class="btn btn-sm" onClick=${() => this.stop(s)}>Stop</button>`}
      ${canRerun(s) && html`<button type="button" class="btn btn-sm" disabled=${!!this.state.busy[s.id]} onClick=${() => this.again(s)}>Rerun</button>`}
      ${this.state.errors[s.id] && html`<span role="alert" class="error">${this.state.errors[s.id]}</span>`}</div>`;
  }

  primary(s) {
    const a = rowAction(s);
    if (!a) return null;
    if (a.kind === 'terminal') {
      return a.command
        ? html`<details><summary>${a.label}</summary><code>${a.command}</code></details>`
        : html`<span class="muted">${a.label}: unavailable, no resume command recorded</span>`;
    }
    return html`<button type="button" disabled=${!!this.state.busy[s.id]} onClick=${() => this.resume(s.id)}>${a.label}</button>`;
  }

  row(s, child = false) {
    const o = rowOutcome(s);
    const known = OUTCOMES.includes(o) ? o : 'unknown';
    return html`
      <tr class=${'row-open' + (child ? ' grp-child' : '')} key=${s.id} onClick=${(e) => rowClickOpens(e, globalThis.getSelection?.()?.toString()) && (location.hash = sessionHref(s))}>
        <td class="cmd" title=${s.command || ''}><a href=${sessionHref(s)}>${s.command ? cmdLabel(s) : s.id}</a></td>
        <td title=${s.repo || ''}>${s.repo ? shortRepo(s.repo) : DASH}</td>
        <td>${fmtTime(s.started_at)}</td>
        <td>${fmtTime(s.ended_at)}</td>
        <td><span class=${'chip chip-' + known}>${known}</span></td>
        <td>${fmtCost(s.cost)}</td>
        <td class="mono" title=${tokensTitle(s.tokens)}>${tokensText(s.tokens) || '—'}</td>
        <td>${this.action(s)}</td>
      </tr>
    `;
  }

  rows({ groups }) {
    const linked = groups.some((g) => g.link);
    return groups.flatMap((g) => {
      if (g.flat || (g.link && g.items.length === 1)) return g.items.map((s) => this.row(s));
      if (g.other && !linked) return g.items.map((s) => this.row(s));
      const t = costTotals([], g.items).shown;
      const head = g.link
        ? html`<a href=${ghUrl(g.link)} target="_blank" rel="noopener noreferrer">${g.link}</a><span class="muted"> · ${g.items.length} sessions · ${fmtCost(t)} · latest ${rowOutcome(g.items[0])}</span>`
        : html`Other<span class="muted"> · ${g.total} sessions</span>`;
      return [html`<tr class="grp-head" key=${`g:${g.key}`}><td colspan="8">${head}</td></tr>`, ...g.items.map((s) => this.row(s, !!g.link))];
    });
  }

  table(rows) {
    return html`
      <div class="table-wrap">
        <table class="history">
          <thead>
            <tr>
              <th scope="col">Command</th>
              <th scope="col">Repo</th>
              <th scope="col">Started</th>
              <th scope="col">Ended</th>
              <th scope="col">Outcome</th>
              <th scope="col">Cost</th>
              <th scope="col">Tokens</th>
              <th scope="col">Action</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  // Waiting and queued sessions, always visible: not filtered, grouped or paged.
  pinned(sessions) {
    const { waiting, queued } = pinnedSessions(sessions);
    if (!waiting.length && !queued.length) return { ids: null, view: null };
    const part = (title, list) => list.length > 0 && html`<h2>${title} <span class="muted">· ${list.length}</span></h2>${this.table(list.map((s) => this.row(s)))}`;
    return { ids: new Set([...waiting, ...queued].map((s) => s.id)), view: html`<section class="pinned" aria-label="Needs attention">${part('Waiting on you', waiting)}${part('Queued / limited', queued)}</section>` };
  }

  render({ sessions }, { filter, repo, repos, q, limit, grouped }) {
    const path = (repos.find((r) => r.value === repo) || {}).path || '';
    let body;
    let totals = null;
    const pin = sessions ? this.pinned(sessions) : { view: null };
    if (sessions == null) body = html`<p>Loading sessions…</p>`;
    else if (sessions.length === 0) body = html`<p>No sessions yet</p>`;
    else {
      const all = filterSessions(sessions, filter, { path, q });
      const rest = pin.ids ? all.filter((s) => !pin.ids.has(s.id)) : all;
      const page = pageRows(rest, grouped, limit);
      totals = costTotals(sessions, all);
      if (all.length === 0) body = html`<p>No sessions match these filters</p>`;
      else if (rest.length) body = html`
          ${this.table(this.rows(page))}
          ${rest.length > page.shown && html`<p class="more"><button type="button" class="btn" onClick=${() => this.setState({ limit: limit + PAGE })}>Show more</button> <span class="muted">${page.shown} of ${rest.length}</span></p>`}`;
    }
    return html`
      <section class="history-page">
      <h1>Sessions</h1>
      <div class="history-filter">
        <${RepoPicker} id="sessions-repo" repos=${repos} value=${{ repo, path: '' }} onPick=${this.pickRepo} allLabel="All repos" placeholder="All repos" />
        <input type="search" data-search class="field" aria-label="Search sessions" placeholder="Search commands and links" value=${q} onInput=${(e) => this.setState({ q: e.target.value, limit: PAGE })} />
        <label>Outcome
          <select onChange=${(e) => this.setState({ filter: e.target.value, limit: PAGE })}>
            <option value="all" selected=${filter === 'all'}>all</option>
            ${OUTCOMES.map((o) => html`<option value=${o} selected=${filter === o}>${o}</option>`)}
          </select>
        </label>
        <label class="check"><input type="checkbox" checked=${grouped} onChange=${(e) => this.setState({ grouped: e.target.checked })} /> Group by issue/PR</label>
        <button type="button" class="btn" onClick=${() => openCleanup()}>Clean up…</button>
      </div>
      ${totals && html`<p class="cost-strip muted" role="status">Today <b>${fmtCost(totals.today)}</b> · last 7 days <b>${fmtCost(totals.week)}</b> · these filters <b>${fmtCost(totals.shown)}</b></p>`}
      ${pin.view}
      ${body}
      </section>
    `;
  }
}
