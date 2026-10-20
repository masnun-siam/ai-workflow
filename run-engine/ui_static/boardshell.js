import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { poll } from './app.js';
import { loadPref, savePref } from './fmt.js';
import { RepoPicker, loadRepoList } from './repopicker.js';

const html = htm.bind(h);

export const REPO_PREF = 'aiw.boardRepo';
// ponytail: one cadence. The server polls GitHub at 60s/15s but serves boards from memory, so a flat 15s costs nothing.
export const BOARD_POLL_MS = 15000;

export const boardUrl = (path, repo) => `${path}?repo=${encodeURIComponent(repo)}`;

// What the shell shows: pick a repo, a skeleton on the first fetch, an error with no data yet, or the board.
export function boardView({ repo, data, error }) {
  if (!repo) return 'pick';
  if (data) return 'data';
  return error ? 'unavailable' : 'skeleton';
}

// POST/PUT JSON; resolves { ok, data, error } and never throws.
export async function sendJson(method, url, body) {
  try {
    const res = await fetch(url, { method, headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    return res.ok ? { ok: true, data } : { ok: false, status: res.status, error: data.error || `HTTP ${res.status}` };
  } catch {
    return { ok: false, error: 'Could not reach the aiw server' };
  }
}

export const fetchedText = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
};

// <BoardShell title path render=${(data, { repo, reload }) => vnode}>. Keeps the last data when a poll fails.
export class BoardShell extends Component {
  state = { repo: loadPref(globalThis.localStorage, REPO_PREF), repos: [], data: null, error: false };

  componentDidMount() {
    loadRepoList(true).then((list) => !this.gone && this.setState({ repos: list.map((r) => ({ value: r.slug, name: r.name || r.slug, path: r.path || '' })) }));
    this.start();
  }

  componentWillUnmount() {
    this.gone = true;
    if (this.stop) this.stop();
  }

  start() {
    if (this.stop) this.stop();
    this.stop = null;
    const { repo } = this.state;
    if (!repo) return;
    this.stop = poll(() => boardUrl(this.props.path, repo), BOARD_POLL_MS, (r) => {
      if (this.gone || this.state.repo !== repo) return;
      if (r.ok) this.setState({ data: r.data, error: false });
      else if (!this.state.data) this.setState({ error: true }); // keep last data on later failures
    });
  }

  reload = () => this.start();

  pick = ({ repo }) => {
    savePref(globalThis.localStorage, REPO_PREF, repo || '');
    this.setState({ repo: repo || '', data: null, error: false }, () => this.start());
  };

  render({ title, render }, { repo, repos, data, error }) {
    const view = boardView({ repo, data, error });
    const picker = html`<div class="board-bar"><${RepoPicker} id="board-repo" repos=${repos} value=${{ repo, path: '' }} onPick=${this.pick} placeholder="Choose a repo" /></div>`;
    let body;
    if (view === 'pick') body = html`<p class="board-empty" role="status">Pick a repo to see its ${title.toLowerCase()} board.</p>`;
    else if (view === 'skeleton') body = html`<div class="board-skeleton" role="status" aria-label="Loading"><div class="skeleton-col"></div><div class="skeleton-col"></div><div class="skeleton-col"></div></div>`;
    else if (view === 'unavailable') body = html`<p class="board-empty" role="status">${title} unavailable, retrying…</p>`;
    else {
      const when = data.fetched_at ? fetchedText(data.fetched_at) : '';
      body = html`
        ${data.stale && html`<p class="stale-banner" role="status">GitHub data is stale${when ? ` (last fetched ${when})` : ''}. Showing the last known board.</p>`}
        ${render(data, { repo, reload: this.reload })}`;
    }
    return html`<section class="board-page"><div class="board-head"><h1>${title}</h1>${picker}</div>${body}</section>`;
  }
}
