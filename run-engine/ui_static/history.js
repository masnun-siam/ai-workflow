import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';

import { formatWhen, shortRepo } from './fmt.js';

const html = htm.bind(h);

const DASH = '—';
const OUTCOMES = ['starting', 'running', 'waiting', 'done', 'failed', 'stopped'];

export function rowOutcome(s) {
  return s.outcome === 'waiting' || s.waiting === true ? 'waiting' : s.outcome;
}

export function transcriptHref(s) {
  const l = s.link;
  if (l && l.owner && l.repo && Number.isInteger(l.issue) && l.issue >= 1) {
    return `#/run/${encodeURIComponent(l.owner)}/${encodeURIComponent(l.repo)}/${l.issue}`;
  }
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
    case 'stopped':
      return { kind: 'post', label: 'Resume', method: 'POST', url: `/api/sessions/${encodeURIComponent(s.id)}/resume` };
    case 'running':
    case 'starting':
      return { kind: 'link', label: 'Open', href: transcriptHref(s) };
    default:
      return null;
  }
}

export function filterSessions(list, filter) {
  return filter === 'all' ? list : list.filter((s) => rowOutcome(s) === filter);
}

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

const orDash = (v) => (v == null || v === '' ? DASH : v);

export class History extends Component {
  state = { filter: 'all', busy: {}, errors: {} };

  // setState is async in preact, so a same-tick double click needs its own guard.
  inflight = new Set();

  resume = async (id) => {
    if (this.inflight.has(id)) return;
    this.inflight.add(id);
    this.setState((st) => ({ busy: { ...st.busy, [id]: true }, errors: { ...st.errors, [id]: null } }));
    const r = await resumeSession(id);
    this.inflight.delete(id);
    this.setState((st) => ({ busy: { ...st.busy, [id]: false }, errors: { ...st.errors, [id]: r.ok ? null : r.error } }));
  };

  action(s) {
    const a = rowAction(s);
    if (!a) return null;
    const err = this.state.errors[s.id];
    if (a.kind === 'link') return html`<a href=${a.href}>${a.label}</a>`;
    if (a.kind === 'terminal') {
      return a.command
        ? html`<details><summary>${a.label}</summary><code>${a.command}</code></details>`
        : html`<span class="muted">${a.label}: unavailable, no resume command recorded</span>`;
    }
    return html`
      <button type="button" disabled=${!!this.state.busy[s.id]} onClick=${() => this.resume(s.id)}>${a.label}</button>
      ${err ? html`<span role="alert" class="error">${err}</span>` : null}
    `;
  }

  row(s) {
    const o = rowOutcome(s);
    const known = OUTCOMES.includes(o) ? o : 'unknown';
    return html`
      <tr>
        <td class="cmd" title=${s.command || ''}>${orDash(s.command)}</td>
        <td title=${s.repo || ''}>${s.repo ? shortRepo(s.repo) : DASH}</td>
        <td>${fmtTime(s.started_at)}</td>
        <td>${fmtTime(s.ended_at)}</td>
        <td><span class=${'chip chip-' + known}>${known}</span></td>
        <td>${fmtCost(s.cost)}</td>
        <td><a href=${sessionHref(s)}>Transcript</a></td>
        <td>${this.action(s)}</td>
      </tr>
    `;
  }

  render({ sessions }, { filter }) {
    let body;
    if (sessions == null) body = html`<p>Loading sessions…</p>`;
    else if (sessions.length === 0) body = html`<p>No sessions yet</p>`;
    else {
      const rows = filterSessions(sessions, filter);
      body = rows.length === 0
        ? html`<p>No sessions match this outcome</p>`
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
                  <th scope="col">Transcript</th>
                  <th scope="col">Action</th>
                </tr>
              </thead>
              <tbody>${rows.map((s) => this.row(s))}</tbody>
            </table>
          </div>`;
    }
    return html`
      <section>
      <div class="history-head">
        <h1>Sessions</h1>
        <span class="muted">Kept on disk · survives UI restarts</span>
      </div>
      <div class="history-filter">
        <label>Outcome
          <select onChange=${(e) => this.setState({ filter: e.target.value })}>
            <option value="all" selected=${filter === 'all'}>all</option>
            ${OUTCOMES.map((o) => html`<option value=${o} selected=${filter === o}>${o}</option>`)}
          </select>
        </label>
      </div>
      ${body}
      </section>
    `;
  }
}
