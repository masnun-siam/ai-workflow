import { h, render, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { Answer } from './answer.js';
import { isWaiting, waitingWatcher, notifyState, requestNotify, notifyWaiting, pageTitle, answerHash } from './notify.js';
import { Board } from './board.js';
// ponytail: import cycle with run.js (it imports poll); safe, neither uses the other at top level.
import { RunDetail } from './run.js';
import { Launcher } from './launcher.js';
import { History } from './history.js';

const html = htm.bind(h);

// Hooks are not vendored, so routing and polling are plain functions plus one class component.
export function parseRoute(hash) {
  let path = String(hash || '').replace(/^#/, '');
  if (path.length > 1 && path.endsWith('/')) path = path.slice(0, -1);
  let seg;
  try {
    seg = path.split('/').slice(1).map(decodeURIComponent);
  } catch {
    return { name: 'notfound', params: {} };
  }
  if (path === '' || path === '/') return { name: 'board', params: {} };
  const [a, ...rest] = seg;
  if (a === 'new' && !rest.length) return { name: 'new', params: {} };
  if (a === 'sessions' && !rest.length) return { name: 'sessions', params: {} };
  if (a === 'answer' && rest.length === 1 && rest[0]) return { name: 'answer', params: { session: rest[0] } };
  if (a === 'run' && rest.length === 3 && rest[0] && rest[1] && /^[1-9]\d*$/.test(rest[2])) {
    return { name: 'run', params: { owner: rest[0], repo: rest[1], n: Number(rest[2]) } };
  }
  return { name: 'notfound', params: {} };
}

// /api/sessions items (_public) carry `id` and a boolean `waiting`.
export function sessionList(data) {
  if (Array.isArray(data)) return data;
  return data && Array.isArray(data.sessions) ? data.sessions : null;
}

export function waitingInfo(data) {
  const waiting = (sessionList(data) || []).filter((s) => isWaiting(s));
  return { count: waiting.length, firstId: waiting.length ? waiting[0].id : null };
}

export function headerBadge(offline, data) {
  if (offline) return { kind: 'offline', count: 0, href: null };
  const { count, firstId } = waitingInfo(data);
  if (count > 0) return { kind: 'waiting', count, href: answerHash(firstId) };
  return sessionList(data) ? { kind: 'idle', count: 0, href: null } : null;
}

const FETCH_TIMEOUT_MS = 8000;

export function poll(url, ms, onResult, keepAlive = () => false) {
  let timer = null;
  let inflight = false;
  let stopped = false;

  async function tick() {
    inflight = true;
    timer = null;
    let result;
    try {
      const res = await fetch(typeof url === 'function' ? url() : url, {
        headers: { Accept: 'application/json' },
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
      });
      result = res.ok ? { ok: true, data: await res.json() } : { ok: false, status: res.status };
    } catch {
      result = { ok: false };
    }
    inflight = false;
    if (stopped) return;
    onResult(result);
    if (!document.hidden || keepAlive()) timer = setTimeout(tick, ms);
  }

  function onVisibility() {
    if (document.hidden) {
      if (keepAlive()) return;
      clearTimeout(timer);
      timer = null;
    } else if (!inflight && timer === null) {
      tick();
    }
  }

  document.addEventListener('visibilitychange', onVisibility);
  tick();
  return function stop() {
    stopped = true;
    clearTimeout(timer);
    timer = null;
    document.removeEventListener('visibilitychange', onVisibility);
  };
}

const NAV = [
  ['board', '#/', 'Board'],
  ['sessions', '#/sessions', 'Sessions'],
];

const BELL = html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"></path><path d="M10 21a2 2 0 0 0 4 0"></path></svg>`;

function View({ route, sessions }) {
  switch (route.name) {
    case 'board':
      return html`<${Board} sessions=${sessions} />`;
    case 'run': {
      const { owner, repo, n } = route.params;
      return html`<${RunDetail} key=${`${owner}/${repo}/${n}`} owner=${owner} repo=${repo} n=${n} sessions=${sessions} />`;
    }
    case 'answer':
      return html`<${Answer} session=${route.params.session} key=${route.params.session} />`;
    case 'new':
      return html`<${Launcher} />`;
    case 'sessions':
      return html`<${History} sessions=${sessions} />`;
    default:
      return html`<h1>Page not found</h1><p><a href="#/">Back to Board</a></p>`;
  }
}

export class App extends Component {
  state = { route: parseRoute(globalThis.location?.hash), sessions: null, offline: false, notif: notifyState() };

  onHash = () => this.setState({ route: parseRoute(location.hash) });

  componentDidMount() {
    addEventListener('hashchange', this.onHash);
    this.watch = waitingWatcher();
    this.stop = poll('/api/sessions', 3000, (r) => {
      if (r.ok) {
        const list = sessionList(r.data);
        this.setState({ sessions: list, offline: false });
        document.title = pageTitle(waitingInfo(list).count);
        for (const s of this.watch(list)) notifyWaiting(s);
      } else {
        this.setState({ offline: true });
        document.title = pageTitle(0);
      }
    }, () => notifyState() === 'granted');
  }

  enableNotify = async () => this.setState({ notif: await requestNotify() });

  componentWillUnmount() {
    removeEventListener('hashchange', this.onHash);
    if (this.stop) this.stop();
  }

  render(_, { route, sessions, offline, notif }) {
    const b = headerBadge(offline, sessions);
    let badge = null;
    if (b?.kind === 'offline') badge = html`<span role="status" class="offline">Offline: retrying</span>`;
    else if (b?.kind === 'waiting') badge = html`<a class="badge waiting" href=${b.href}>${BELL}Waiting on you · ${b.count}</a>`;
    else if (b?.kind === 'idle') badge = html`<span class="muted">Nothing waiting</span>`;
    return html`
      <header>
        <a class="brand" href="#/">aiw ui</a>
        <nav aria-label="Main">
          ${NAV.map(([name, href, label]) => html`<a href=${href} aria-current=${route.name === name ? 'page' : undefined}>${label}</a>`)}
        </nav>
        <span class="spacer"></span>
        ${badge}
        ${notif === 'default' && html`<button type="button" class="icon-btn" aria-label="Enable notifications" title="Enable desktop notifications" onClick=${this.enableNotify}>${BELL}</button>`}
        <a class="btn btn--primary" href="#/new" aria-current=${route.name === 'new' ? 'page' : undefined}>New run</a>
      </header>
      <main><${View} route=${route} sessions=${sessions} /></main>
    `;
  }
}

const root = globalThis.document?.getElementById('app');
if (root) render(html`<${App} />`, root);
