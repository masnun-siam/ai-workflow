import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { poll } from './app.js';
import { currentRepo, setRepo } from './fmt.js';
import { RepoPicker, loadRepoList } from './repopicker.js';

const html = htm.bind(h);

// ponytail: one cadence. The server polls GitHub at 60s/15s but serves boards from memory, so a flat 15s costs nothing.
export const BOARD_POLL_MS = 15000;

export const boardUrl = (path, repo, refresh) => `${path}?repo=${encodeURIComponent(repo)}${refresh ? '&refresh=1' : ''}`;

// Stale banner text: still loading, rate limited (and until when), or the fetch error.
export function staleText({ fetched_at, error, retry_at }) {
  if (!fetched_at && !error) return 'Loading from GitHub…';
  const when = fetched_at ? ` Showing the board from ${fetchedText(fetched_at)}.` : '';
  if (error === 'rate limited') return `GitHub rate limit reached${retry_at ? `, retrying at ${fetchedText(retry_at)}` : ''}.${when}`;
  return `Could not refresh from GitHub${error ? `: ${error}` : ''}.${when}`;
}

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

// The poller sends Unix seconds; an ISO string also works.
export const fetchedText = (t) => {
  const d = new Date(typeof t === 'number' ? t * 1000 : t);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
};

// <BoardShell title path render=${(data, { repo, reload }) => vnode}>. Keeps the last data when a poll fails.
export class BoardShell extends Component {
  state = { repo: currentRepo(), repos: [], data: null, error: false };

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

  // Ask the server to fetch now, then poll as usual; the next poll picks up the fresh snapshot.
  refresh = () => {
    const { repo } = this.state;
    if (!repo) return;
    this.setState({ refreshing: true });
    fetch(boardUrl(this.props.path, repo, true), { headers: { Accept: 'application/json' } })
      .catch(() => {})
      .finally(() => setTimeout(() => !this.gone && (this.setState({ refreshing: false }), this.start()), 2000));
  };

  pick = ({ repo }) => {
    setRepo(repo || '');
    this.setState({ repo: repo || '', data: null, error: false }, () => this.start());
  };

  render({ title, render }, { repo, repos, data, error, refreshing }) {
    const view = boardView({ repo, data, error });
    const picker = html`<div class="board-bar"><${RepoPicker} id="board-repo" repos=${repos} value=${{ repo, path: '' }} onPick=${this.pick} placeholder="Choose a repo" /></div>`;
    // Before the first GitHub fetch every PRD looks like it has no issues, so no board (and no wrong actions) yet.
    const skeleton = html`<div class="board-skeleton" role="status" aria-label="Loading"><div class="skeleton-col"></div><div class="skeleton-col"></div><div class="skeleton-col"></div></div>`;
    let body;
    if (view === 'pick') body = html`<p class="board-empty" role="status">Pick a repo to see its ${title.toLowerCase()} board.</p>`;
    else if (view === 'skeleton') body = skeleton;
    else if (view === 'unavailable') body = html`<p class="board-empty" role="status">${title} unavailable, retrying…</p>`;
    else {
      const limited = data.error === 'rate limited';
      body = html`
        ${data.stale && html`<p class="stale-banner" role="status">${staleText(data)}
          ${(data.fetched_at || data.error) && !limited && html` <button type="button" class="btn-link" disabled=${refreshing} onClick=${this.refresh}>${refreshing ? 'Refreshing…' : 'Refresh'}</button>`}</p>`}
        ${data.fetched_at ? render(data, { repo, reload: this.reload }) : skeleton}`;
    }
    return html`<section class="board-page"><div class="board-head"><h1>${title}</h1>${picker}</div>${body}</section>`;
  }
}
