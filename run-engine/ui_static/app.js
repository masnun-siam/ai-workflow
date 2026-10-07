import { h, render, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { Board } from './board.js';
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

// Assumes /api/sessions (task 12) items carry `status` and `id`; pin these names on task 12.
export function sessionList(data) {
  if (Array.isArray(data)) return data;
  return data && Array.isArray(data.sessions) ? data.sessions : null;
}

export function waitingInfo(data) {
  const waiting = (sessionList(data) || []).filter((s) => s && s.status === 'waiting');
  return { count: waiting.length, firstId: waiting.length ? waiting[0].id : null };
}

export function headerBadge(offline, data) {
  if (offline) return { kind: 'offline', count: 0, href: null };
  const { count, firstId } = waitingInfo(data);
  if (count > 0) return { kind: 'waiting', count, href: '#/answer/' + encodeURIComponent(firstId) };
  return sessionList(data) ? { kind: 'idle', count: 0, href: null } : null;
}

export function poll(url, ms, onResult) {
  let timer = null;
  let inflight = false;
  let stopped = false;

  async function tick() {
    inflight = true;
    timer = null;
    let result;
    try {
      const res = await fetch(url, { headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      result = { ok: true, data: await res.json() };
    } catch {
      result = { ok: false };
    }
    inflight = false;
    if (stopped) return;
    onResult(result);
    if (!document.hidden) timer = setTimeout(tick, ms);
  }

  function onVisibility() {
    if (document.hidden) {
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
  ['new', '#/new', 'New run'],
  ['sessions', '#/sessions', 'Sessions'],
];

function View({ route, sessions }) {
  switch (route.name) {
    case 'board':
      return html`<${Board} sessions=${sessions} />`;
    case 'run': {
      const { owner, repo, n } = route.params;
      return html`<h1>Run</h1><p>${owner}/${repo}#${n}</p>`;
    }
    case 'answer':
      return html`<h1>Answer</h1><p>Session ${route.params.session}</p>`;
    case 'new':
      return html`<${Launcher} />`;
    case 'sessions':
      return html`<${History} sessions=${sessions} />`;
    default:
      return html`<h1>Page not found</h1><p><a href="#/">Back to Board</a></p>`;
  }
}

export class App extends Component {
  state = { route: parseRoute(globalThis.location?.hash), sessions: null, offline: false };

  onHash = () => this.setState({ route: parseRoute(location.hash) });

  componentDidMount() {
    addEventListener('hashchange', this.onHash);
    this.stop = poll('/api/sessions', 3000, (r) => {
      if (r.ok) this.setState({ sessions: sessionList(r.data), offline: false });
      else this.setState({ offline: true });
    });
  }

  componentWillUnmount() {
    removeEventListener('hashchange', this.onHash);
    if (this.stop) this.stop();
  }

  render(_, { route, sessions, offline }) {
    const b = headerBadge(offline, sessions);
    let badge = null;
    if (b?.kind === 'offline') badge = html`<span role="status" class="offline">Offline: retrying</span>`;
    else if (b?.kind === 'waiting') badge = html`<a class="badge waiting" href=${b.href}>${b.count} waiting on you</a>`;
    else if (b?.kind === 'idle') badge = html`<span class="muted">Nothing waiting</span>`;
    return html`
      <header>
        <a class="brand" href="#/">aiw</a>
        <nav aria-label="Main">
          ${NAV.map(([name, href, label]) => html`<a href=${href} aria-current=${route.name === name ? 'page' : undefined}>${label}</a>`)}
        </nav>
        ${badge}
      </header>
      <main><${View} route=${route} sessions=${sessions} /></main>
    `;
  }
}

const root = globalThis.document?.getElementById('app');
if (root) render(html`<${App} />`, root);
