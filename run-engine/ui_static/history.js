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
    case 'queued':
    case 'running':
    case 'starting':
      return { kind: 'link', label: 'Open', href: transcriptHref(s) };
    case 'done':
      return { kind: 'link', label: 'Open', href: transcriptHref(s) };
    default:
      return null;
  }
}

export const PAGE = 50;

// Outcome, repo (a checkout path) and a text search over the command and its link.
export function filterSessions(list, filter, { path = '', q = '' } = {}) {
  const needle = q.trim().toLowerCase();
  return list.filter((s) => (filter === 'all' || rowOutcome(s) === filter)
    && (!path || (s.repo_path || s.repo) === path)
    && (!needle || `${s.command || ''} ${s.link || ''}`.toLowerCase().includes(needle)));
}

// Cost of today, the last 7 days and the given list (the rows on screen). `now` in ms.
export function costTotals(all, shown, now = Date.now()) {
  const day = new Date(now); day.setHours(0, 0, 0, 0);
  const sum = (xs) => xs.reduce((t, s) => t + (typeof s.cost === 'number' ? s.cost : 0), 0);
  const since = (ms) => all.filter((s) => s.started_at && new Date(s.started_at).getTime() >= ms);
  return { today: sum(since(day.getTime())), week: sum(since(now - 7 * 86400000)), shown: sum(shown) };
}

// Sessions grouped by the issue or PR they worked on (their link), newest group first; unlinked ones stay alone.
export function groupSessions(list) {
  const groups = [];
  const by = new Map();
  for (const s of list) {
    if (!s.link) { groups.push({ key: s.id, link: null, items: [s] }); continue; }
    if (!by.has(s.link)) { const g = { key: s.link, link: s.link, items: [] }; by.set(s.link, g); groups.push(g); }
    by.get(s.link).items.push(s);
  }
  return groups;
}

export const linkLabel = (url) => { const m = /\/(issues|pull)\/(\d+)/.exec(url || ''); return m ? `${m[1] === 'pull' ? 'PR' : 'Issue'} #${m[2]}` : url; };


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
export function cmdLabel(s) {
  const label = sessionLabel(s.command);
  return label !== s.command && s.link && s.link.issue ? `${label} #${s.link.issue}` : label;
}


export class History extends Component {
  state = { filter: 'all', busy: {}, errors: {}, repo: currentRepo(), repos: [], q: '', limit: PAGE, grouped: false };

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
    if (a.kind === 'link') return html`<a href=${a.href}>${a.label}</a>`;
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
      <tr class=${child ? 'grp-child' : ''} key=${s.id}>
        <td class="cmd" title=${s.command || ''}>${s.command ? html`<a href=${sessionHref(s)}>${cmdLabel(s)}</a>` : DASH}</td>
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

  rows(shown, grouped) {
    if (!grouped) return shown.map((s) => this.row(s));
    return groupSessions(shown).flatMap((g) => {
      if (!g.link || g.items.length === 1) return g.items.map((s) => this.row(s));
      const t = costTotals([], g.items).shown;
      return [html`<tr class="grp-head" key=${`g:${g.key}`}><td colspan="8"><a href=${g.link} target="_blank" rel="noopener noreferrer">${linkLabel(g.link)}</a>
        <span class="muted"> · ${g.items.length} sessions · ${fmtCost(t)} · latest ${rowOutcome(g.items[0])}</span></td></tr>`, ...g.items.map((s) => this.row(s, true))];
    });
  }

  render({ sessions }, { filter, repo, repos, q, limit, grouped }) {
    const path = (repos.find((r) => r.value === repo) || {}).path || '';
    let body;
    let totals = null;
    if (sessions == null) body = html`<p>Loading sessions…</p>`;
    else if (sessions.length === 0) body = html`<p>No sessions yet</p>`;
    else {
      const all = filterSessions(sessions, filter, { path, q });
      const shown = all.slice(0, limit);
      totals = costTotals(sessions, all);
      body = all.length === 0
        ? html`<p>No sessions match these filters</p>`
        : html`
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
              <tbody>${this.rows(shown, grouped)}</tbody>
            </table>
          </div>
          ${all.length > shown.length && html`<p class="more"><button type="button" class="btn" onClick=${() => this.setState({ limit: limit + PAGE })}>Show ${Math.min(PAGE, all.length - shown.length)} more</button> <span class="muted">${shown.length} of ${all.length}</span></p>`}`;
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
      ${body}
      </section>
    `;
  }
}
