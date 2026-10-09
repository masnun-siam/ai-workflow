import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { runHref, stationLabel } from './board.js';
import { shortRepo } from './fmt.js';

const html = htm.bind(h);

const TYPING = new Set(['INPUT', 'TEXTAREA', 'SELECT']);
export const isTyping = (el) => !!el && (TYPING.has(el.tagName) || el.isContentEditable === true);

const go = (hash) => ({ type: 'goto', hash });

// Maps a keydown to what the app should do, or null. `chord` is true right after a bare `g`.
// Cmd/Ctrl+K and Escape work everywhere; every other key is ignored while typing in a field.
export function keyIntent(e, chord = false) {
  const key = e.key;
  if ((e.metaKey || e.ctrlKey) && String(key).toLowerCase() === 'k') return { type: 'palette' };
  if (e.metaKey || e.ctrlKey || e.altKey) return null;
  if (key === 'Escape') return { type: 'escape' };
  if (isTyping(e.target)) return null;
  if (chord) return { b: go('#/'), s: go('#/sessions'), d: go('#/dispatch'), n: go('#/new') }[key] || null;
  switch (key) {
    case 'g': return { type: 'chord' };
    case 'n': return go('#/new');
    case '?': return { type: 'sheet' };
    case '/': return { type: 'search' };
    case 'j': case 'ArrowDown': return { type: 'move', dir: 'down' };
    case 'k': case 'ArrowUp': return { type: 'move', dir: 'up' };
    case 'h': case 'ArrowLeft': return { type: 'move', dir: 'left' };
    case 'l': case 'ArrowRight': return { type: 'move', dir: 'right' };
    default: return null;
  }
}

// Board navigation on a grid of per-column card counts. `cur` is [column, row] or null.
export function moveTarget(counts, cur, dir) {
  const filled = counts.map((n, i) => (n > 0 ? i : -1)).filter((i) => i >= 0);
  if (!filled.length) return null;
  if (!cur) return [filled[0], 0];
  let [c, r] = cur;
  if (dir === 'down') r = Math.min(r + 1, counts[c] - 1);
  else if (dir === 'up') r = Math.max(r - 1, 0);
  else {
    const next = filled[filled.indexOf(c) + (dir === 'right' ? 1 : -1)];
    if (next === undefined) return cur;
    c = next;
    r = Math.min(r, counts[c] - 1);
  }
  return [c, r];
}

// DOM adapter for moveTarget. Returns false when there is no board on screen.
export function moveFocus(dir, doc = document) {
  const columns = [...doc.querySelectorAll('.board .column')].map((col) => [...col.querySelectorAll('[data-card]')]);
  if (!columns.length) return false;
  const active = doc.activeElement && doc.activeElement.closest ? doc.activeElement.closest('[data-card]') : null;
  let cur = null;
  columns.forEach((cards, c) => {
    const r = cards.indexOf(active);
    if (r >= 0) cur = [c, r];
  });
  const next = moveTarget(columns.map((c) => c.length), cur, dir);
  if (next) {
    const el = columns[next[0]][next[1]];
    el.focus({ preventScroll: true });
    el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }
  return true;
}

export function paletteItems({ board, sessions, afk }) {
  const items = [
    { id: 'nav-board', group: 'Go to', label: 'Board', detail: 'g b', href: '#/' },
    { id: 'nav-sessions', group: 'Go to', label: 'Sessions', detail: 'g s', href: '#/sessions' },
    { id: 'nav-dispatch', group: 'Go to', label: 'Dispatch', detail: 'g d · run a batch of issues', href: '#/dispatch' },
    { id: 'nav-new', group: 'Go to', label: 'New run', detail: 'n', href: '#/new' },
    { id: 'nav-settings', group: 'Go to', label: 'Settings', detail: 'Claude commands', href: '#/settings' },
    afk?.active
      ? { id: 'afk', group: 'Autopilot', label: "I'm back", detail: 'end AFK mode now', event: 'aiw:afk-back' }
      : { id: 'afk', group: 'Autopilot', label: 'Go AFK…', detail: 'autopilot for 30 min to 4 hours', event: 'aiw:afk' },
  ];
  for (const col of (board && board.columns) || []) {
    for (const card of col.cards || []) {
      items.push({
        id: `run-${card.owner}/${card.repo}#${card.issue}`,
        group: 'Run',
        label: `#${card.issue} ${card.title || card.repo}`,
        detail: `${card.repo} · ${stationLabel(col.key)}`,
        href: runHref(card),
      });
    }
  }
  for (const s of sessions || []) {
    items.push({
      id: `session-${s.id}`,
      group: 'Session',
      label: s.command || 'session',
      detail: `${shortRepo(s.repo)} · ${s.outcome}`,
      href: s.outcome === 'waiting' ? `#/answer/${encodeURIComponent(s.id)}` : `#/session/${encodeURIComponent(s.id)}`,
    });
  }
  return items;
}

// Every whitespace-separated word must appear somewhere in the item; capped so the list stays short.
export function filterItems(items, query, limit = 8) {
  const words = String(query || '').toLowerCase().split(/\s+/).filter(Boolean);
  const hit = (it) => {
    const hay = `${it.label} ${it.detail} ${it.group}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  };
  return items.filter(hit).slice(0, limit);
}

export const SHORTCUTS = [
  ['⌘K / Ctrl+K', 'Command palette'],
  ['g then b', 'Go to Board'],
  ['g then s', 'Go to Sessions'],
  ['g then d', 'Go to Dispatch'],
  ['n', 'New run'],
  ['j / k', 'Next / previous card'],
  ['h / l', 'Previous / next column'],
  ['Enter', 'Open focused card'],
  ['/', 'Focus search or filter'],
  ['Esc', 'Close dialog, or go back'],
  ['?', 'This sheet'],
];

export class Palette extends Component {
  state = { q: '', active: 0, board: null };

  async componentDidMount() {
    try {
      const res = await fetch('/board.json', { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(8000) });
      if (res.ok && !this.gone) this.setState({ board: await res.json() });
    } catch {
      // palette still offers navigation and sessions without board data
    }
  }

  componentWillUnmount() {
    this.gone = true;
  }

  items() {
    return filterItems(paletteItems({ board: this.state.board, sessions: this.props.sessions, afk: this.props.afk }), this.state.q);
  }

  pick = (item) => {
    this.props.onClose();
    if (item.event) dispatchEvent(new CustomEvent(item.event));
    else location.hash = item.href;
  };

  onKey = (e) => {
    const items = this.items();
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const n = items.length || 1;
      this.setState({ active: (this.state.active + (e.key === 'ArrowDown' ? 1 : n - 1)) % n });
    } else if (e.key === 'Enter' && items.length) {
      e.preventDefault();
      this.pick(items[Math.min(this.state.active, items.length - 1)]);
    }
  };

  render({ onClose }, { q, active }) {
    const items = this.items();
    return html`<div class="overlay" onMouseDown=${(e) => e.target === e.currentTarget && onClose()}>
      <div class="dialog palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <input class="field" autofocus role="combobox" aria-expanded="true" aria-controls="palette-list" aria-autocomplete="list"
          aria-activedescendant=${items.length ? 'pal-' + Math.min(active, items.length - 1) : undefined}
          placeholder="Jump to a run, session or page…" value=${q}
          onInput=${(e) => this.setState({ q: e.target.value, active: 0 })} onKeyDown=${this.onKey}
          ref=${(el) => el && !this.focused && ((this.focused = true), el.focus())} />
        <ul id="palette-list" role="listbox" aria-label="Results">
          ${items.length
            ? items.map((it, i) => html`<li id=${'pal-' + i} role="option" key=${it.id} aria-selected=${i === Math.min(active, items.length - 1) ? 'true' : 'false'}
                onMouseEnter=${() => this.setState({ active: i })} onClick=${() => this.pick(it)}>
                <span class="pal-label">${it.label}</span><span class="pal-detail mono">${it.detail}</span><span class="pal-group">${it.group}</span>
              </li>`)
            : html`<li class="pal-empty">No matches</li>`}
        </ul>
      </div>
    </div>`;
  }
}

export function Shortcuts({ onClose }) {
  return html`<div class="overlay" onMouseDown=${(e) => e.target === e.currentTarget && onClose()}>
    <div class="dialog" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts">
      <h2>Keyboard shortcuts</h2>
      <dl class="keys">
        ${SHORTCUTS.map(([k, d]) => html`<dt><kbd>${k}</kbd></dt><dd>${d}</dd>`)}
      </dl>
      <button type="button" class="btn" onClick=${onClose}>Close</button>
    </div>
  </div>`;
}
