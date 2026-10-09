import { h, render, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { Answer } from './answer.js';
import { isWaiting, waitingWatcher, notifyState, requestNotify, notifyWaiting, pageTitle, answerHash } from './notify.js';
import { Board } from './board.js';
// ponytail: import cycle with run.js (it imports poll); safe, neither uses the other at top level.
import { RunDetail } from './run.js';
import { Launcher } from './launcher.js';
import { History } from './history.js';
import { Session } from './session.js';
import { Settings } from './settings.js';
import { Dispatch, PipelineDetail } from './dispatch.js';
import { Flow } from './flow.js';
import { clockText } from './fmt.js';
import { toast } from './toast.js';
import { CleanupDialog } from './cleanup.js';
import { IssueDialog } from './issue.js';
import { PrDialog } from './pr.js';
import { keyIntent, moveFocus, Palette, Shortcuts } from './keys.js';
import { AfkControl, AfkSummary, afkPost } from './afk.js';

const html = htm.bind(h);

// Hooks are not vendored, so routing and polling are plain functions plus one class component.
// Issue numbers from a `?issues=1,2` query; hash input is untrusted, so only plain digits pass.
const queryIssues = (q) => (q.get('issues') || '').split(',').filter((s) => /^\d+$/.test(s)).map(Number);

export function parseRoute(hash) {
  let path = String(hash || '').replace(/^#/, '');
  const qi = path.indexOf('?');
  const query = new URLSearchParams(qi < 0 ? '' : path.slice(qi + 1));
  if (qi >= 0) path = path.slice(0, qi);
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
  if (a === 'settings' && !rest.length) return { name: 'settings', params: {} };
  if (a === 'dispatch' && !rest.length) {
    const issues = queryIssues(query);
    return issues.length ? { name: 'dispatch', params: {}, issues } : { name: 'dispatch', params: {} };
  }
  if (a === 'flow' && !rest.length) {
    // folder/prd become headless session args: one line, bounded, so the input shows all that is sent
    const get = (k) => (query.get(k) || '').replace(/[\u0000-\u001f\u007f]+/g, ' ').slice(0, 500);
    return { name: 'flow', params: { repo: get('repo'), folder: get('folder'), prd: get('prd'), issues: queryIssues(query), sid: get('sid') } };
  }
  if (a === 'dispatch' && rest.length === 1 && /^p-\d{14}-[0-9a-f]{6}$/.test(rest[0])) return { name: 'pipeline', params: { id: rest[0] } };
  if (a === 'session' && rest.length === 1 && rest[0]) return { name: 'session', params: { id: rest[0] } };
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

export const NAV = [
  ['board', '#/', 'Board'],
  ['flow', '#/flow', 'Flow'],
  ['dispatch', '#/dispatch', 'Dispatch'],
  ['sessions', '#/sessions', 'Sessions'],
];

const BELL = html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"></path><path d="M10 21a2 2 0 0 0 4 0"></path></svg>`;

// One header chip per account that is limited or near its limit.
export function limitChips(limits, commands) {
  const label = (cmd) => (commands.find((c) => c.cmd === cmd) || {}).label || cmd;
  return Object.entries(limits || {}).flatMap(([cmd, v]) => {
    if (v.limited_until) return [{ kind: 'limited', text: `${label(cmd)} · limited until ${clockText(v.limited_until)}` }];
    const w = v.warning;
    if (w && typeof w.utilization === 'number') return [{ kind: 'warn', text: `${label(cmd)} · ${w.type === 'seven_day' ? '7d' : w.type === 'five_hour' ? '5h' : 'usage'} ${Math.round(w.utilization * 100)}%` }];
    return [];
  });
}

const GEAR = html`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"></path></svg>`;

function View({ route, sessions, limits }) {
  switch (route.name) {
    case 'board':
      return html`<${Board} sessions=${sessions} />`;
    case 'run': {
      const { owner, repo, n } = route.params;
      return html`<${RunDetail} key=${`${owner}/${repo}/${n}`} owner=${owner} repo=${repo} n=${n} sessions=${sessions} />`;
    }
    case 'answer':
      return html`<${Answer} session=${route.params.session} key=${route.params.session} />`;
    case 'session':
      return html`<${Session} key=${route.params.id} id=${route.params.id} />`;
    case 'new':
      return html`<${Launcher} limits=${limits} />`;
    case 'settings':
      return html`<${Settings} />`;
    case 'flow':
      return html`<${Flow} key=${JSON.stringify(route.params)} route=${route} />`;
    case 'dispatch':
      return html`<${Dispatch} key=${(route.issues || []).join(',')} issues=${route.issues} />`;
    case 'pipeline':
      return html`<${PipelineDetail} key=${route.params.id} id=${route.params.id} />`;
    case 'sessions':
      return html`<${History} sessions=${sessions} />`;
    default:
      return html`<h1>Page not found</h1><p><a href="#/">Back to Board</a></p>`;
  }
}

export class App extends Component {
  state = { route: parseRoute(globalThis.location?.hash), sessions: null, limits: {}, afk: null, commands: [], offline: false, notif: notifyState(), palette: false, sheet: false, cleanup: null, peek: null };

  onHash = () => {
    this.setState({ route: parseRoute(location.hash) });
    this.loadCommands();
  };

  // Account labels for the header chips; reloaded on navigation so Settings edits show up.
  async loadCommands() {
    try {
      const res = await fetch('/api/settings', { headers: { Accept: 'application/json' } });
      if (res.ok && !this.gone) this.setState({ commands: (await res.json()).commands || [] });
    } catch {
      // chips fall back to the raw command
    }
  }

  prev = {};

  // One global key handler: shortcuts are ignored while typing, except Cmd/Ctrl+K and Escape.
  chordAt = 0;

  onKey = (e) => {
    const intent = keyIntent(e, Date.now() - this.chordAt < 800);
    this.chordAt = 0;
    if (!intent) return;
    const { palette, sheet, cleanup, peek, route } = this.state;
    switch (intent.type) {
      case 'chord': this.chordAt = Date.now(); break;
      case 'goto': e.preventDefault(); location.hash = intent.hash; break;
      case 'palette': e.preventDefault(); this.openDialog({ palette: !palette, sheet: false }); break;
      case 'sheet': e.preventDefault(); this.openDialog({ sheet: !sheet, palette: false }); break;
      case 'search': {
        const el = document.querySelector('[data-search]');
        if (el) { e.preventDefault(); el.focus(); }
        break;
      }
      case 'move': if (!palette && !sheet && !cleanup && !peek && moveFocus(intent.dir)) e.preventDefault(); break;
      case 'escape':
        if (palette || sheet || cleanup || peek) this.closeDialogs();
        else if (['run', 'session', 'answer', 'pipeline'].includes(route.name)) history.length > 1 ? history.back() : (location.hash = '#/');
        break;
    }
  };

  // Remembers what had focus so closing a dialog puts it back.
  openDialog(next) {
    const opening = next.palette || next.sheet || next.cleanup || next.peek;
    const { palette, sheet, cleanup, peek } = this.state;
    if (opening && !palette && !sheet && !cleanup && !peek) this.returnFocus = document.activeElement;
    this.setState(next);
    if (!opening && this.returnFocus && this.returnFocus.focus) this.returnFocus.focus();
  }

  closeDialogs = () => this.openDialog({ palette: false, sheet: false, cleanup: null, peek: null });

  onPeek = (e) => this.openDialog({ palette: false, sheet: false, cleanup: null, peek: e.detail });

  onCleanup = (e) => this.openDialog({ palette: false, sheet: false, cleanup: { only: e.detail?.key || null } });

  componentDidMount() {
    addEventListener('hashchange', this.onHash);
    addEventListener('keydown', this.onKey);
    addEventListener('aiw:cleanup', this.onCleanup);
    addEventListener('aiw:peek', this.onPeek);
    addEventListener('aiw:afk-back', this.onAfkBack);
    this.watch = waitingWatcher();
    this.loadCommands();
    this.stop = poll('/api/sessions', 3000, (r) => {
      if (r.ok) {
        const list = sessionList(r.data);
        this.setAfk((r.data && r.data.afk) || null);
        this.setState({ sessions: list, limits: (r.data && r.data.limits) || {}, offline: false });
        for (const s of list || []) {
          if (this.prev[s.id] === 'limited' && ['starting', 'running'].includes(s.outcome)) toast(`Resumed after limit: ${s.command || 'run'}`);
          this.prev[s.id] = s.outcome;
        }
        const away = !!this.state.afk?.active;  // autopilot handles or holds these; no badge count, no pings
        document.title = pageTitle(away ? 0 : waitingInfo(list).count);
        for (const s of this.watch(list)) if (!away) notifyWaiting(s);
      } else {
        this.setState({ offline: true });
        document.title = pageTitle(0);
      }
    }, () => notifyState() === 'granted');
  }

  // The whole app re-themes from one attribute while autopilot is on.
  setAfk = (afk) => {
    document.documentElement.toggleAttribute('data-afk', !!afk?.active);
    this.setState({ afk });
  };

  onAfkBack = async () => {
    const r = await afkPost('/stop');
    if (r) this.setAfk(r);
  };

  dismissAfk = async () => {
    const r = await afkPost('/dismiss');
    if (r) this.setAfk(r);
  };

  enableNotify = async () => this.setState({ notif: await requestNotify() });

  componentWillUnmount() {
    this.gone = true;
    removeEventListener('hashchange', this.onHash);
    removeEventListener('keydown', this.onKey);
    removeEventListener('aiw:cleanup', this.onCleanup);
    removeEventListener('aiw:peek', this.onPeek);
    removeEventListener('aiw:afk-back', this.onAfkBack);
    if (this.stop) this.stop();
  }

  render(_, { route, sessions, limits, afk, commands, offline, notif, palette, sheet, cleanup, peek }) {
    const b = headerBadge(offline, afk?.active ? [] : sessions);
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
        <button type="button" class="btn kbd-hint" aria-label="Open command palette" onClick=${() => this.openDialog({ palette: true, sheet: false })}>Search <kbd>⌘K</kbd></button>
        ${limitChips(limits, commands).map((c) => html`<span class=${`chip chip-${c.kind === 'limited' ? 'limited' : 'waiting'}`} role="status">${c.text}</span>`)}
        <${AfkControl} afk=${afk} onChange=${this.setAfk} />
        ${!afk?.active && badge}
        <a class="icon-btn" href="#/settings" aria-label="Settings" title="Settings" aria-current=${route.name === 'settings' ? 'page' : undefined}>${GEAR}</a>
        ${notif === 'default' && html`<button type="button" class="icon-btn" aria-label="Enable notifications" title="Enable desktop notifications" onClick=${this.enableNotify}>${BELL}</button>`}
        <a class="btn btn--primary" href="#/new" aria-current=${route.name === 'new' ? 'page' : undefined}>New run</a>
      </header>
      <main>
        ${afk?.summary && html`<${AfkSummary} summary=${afk.summary} onDismiss=${this.dismissAfk} />`}
        <${View} route=${route} sessions=${sessions} limits=${limits} />
      </main>
      ${palette && html`<${Palette} sessions=${sessions} afk=${afk} onClose=${this.closeDialogs} />`}
      ${sheet && html`<${Shortcuts} onClose=${this.closeDialogs} />`}
      ${peek && peek.kind === 'issue' && html`<${IssueDialog} key=${`${peek.owner}/${peek.repo}#${peek.n}`} owner=${peek.owner} repo=${peek.repo} issue=${peek.n} onClose=${this.closeDialogs} />`}
      ${peek && peek.kind === 'pr' && html`<${PrDialog} key=${`${peek.owner}/${peek.repo}#${peek.n}`} owner=${peek.owner} repo=${peek.repo} pr=${peek.n} onClose=${this.closeDialogs} />`}
      ${cleanup && html`<${CleanupDialog} only=${cleanup.only} onClose=${this.closeDialogs} />`}
    `;
  }
}

const root = globalThis.document?.getElementById('app');
if (root) render(html`<${App} />`, root);
