import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { toast } from './toast.js';

const html = htm.bind(h);

// Any view asks for the dialog by event, so no props travel through the router. `key` narrows it to one run.
export const openCleanup = (key = null) => globalThis.dispatchEvent(new CustomEvent('aiw:cleanup', { detail: { key } }));

export const itemTitle = (it) => (it.owner ? `${it.owner}/${it.repo}#${it.issue}` : it.label);

// Clean items start checked; items with unsaved work start unchecked and need a deliberate tick.
export const preselected = (items) => new Set(items.filter((i) => !i.flags.length).map((i) => i.key));

export function prBadge(it) {
  if (it.status !== 'done') return null;
  if (it.pr_merged === true) return 'PR merged: issue will close';
  return it.pr_merged === false ? 'PR not merged: issue stays open' : 'PR state unknown: issue stays open';
}

async function load() {
  const res = await fetch('/api/cleanup', { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()).items;
}

async function send(items) {
  const res = await fetch('/api/cleanup', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items }) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()).results;
}

export class CleanupDialog extends Component {
  state = { items: null, picked: new Set(), busy: false, error: '', failed: {} };

  async componentDidMount() {
    try {
      const all = await load();
      if (this.gone) return;
      const items = this.props.only ? all.filter((i) => i.key === this.props.only) : all;
      this.setState({ items, picked: preselected(items) });
    } catch (e) {
      if (!this.gone) this.setState({ items: [], error: `Could not load: ${e.message}` });
    }
  }

  componentWillUnmount() {
    this.gone = true;
  }

  toggle = (key) => {
    const picked = new Set(this.state.picked);
    if (!picked.delete(key)) picked.add(key);
    this.setState({ picked });
  };

  confirm = async () => {
    const { items, picked } = this.state;
    const chosen = items.filter((i) => picked.has(i.key));
    this.setState({ busy: true, error: '', failed: {} });
    let results;
    try {
      results = await send(chosen.map((i) => ({ key: i.key, force: i.flags.length > 0 })));
    } catch (e) {
      this.setState({ busy: false, error: `Cleanup failed: ${e.message}` });
      toast(`Cleanup failed: ${e.message}`, 'error');
      return;
    }
    const bad = results.filter((r) => !r.ok);
    const good = results.length - bad.length;
    if (good) toast(`Cleaned ${good} run${good === 1 ? '' : 's'}${results.some((r) => (r.notes || []).some((n) => n === 'issue closed')) ? ', closed merged issues' : ''}`);
    if (!bad.length) return this.props.onClose();
    toast(`${bad.length} could not be cleaned`, 'error');
    const left = items.filter((i) => bad.some((r) => r.key === i.key));
    this.setState({ busy: false, items: left, picked: new Set(), failed: Object.fromEntries(bad.map((r) => [r.key, r.error])) });
  };

  render({ onClose }, { items, picked, busy, error, failed }) {
    const n = picked.size;
    return html`<div class="overlay" onMouseDown=${(e) => e.target === e.currentTarget && onClose()}>
      <div class="dialog cleanup" role="dialog" aria-modal="true" aria-label="Clean up runs">
        <h2>Clean up runs</h2>
        <p class="muted">Removes the worktree, run data and session transcripts. Finished runs also lose their local branch; stopped runs keep it.</p>
        ${items === null && html`<p role="status">Loading…</p>`}
        ${items && !items.length && html`<p class="muted">Nothing to clean up.</p>`}
        ${error && html`<p role="alert" class="error">${error}</p>`}
        ${items && items.length > 0 && html`<ul class="cleanup-list">${items.map((it) => html`
          <li key=${it.key}>
            <label>
              <input type="checkbox" checked=${picked.has(it.key)} disabled=${busy} onChange=${() => this.toggle(it.key)} />
              <span class="mono">${itemTitle(it)}</span>
              <span class=${`chip chip-${it.status}`}>${it.status}</span>
            </label>
            <span class="muted cleanup-facts">${[prBadge(it), it.status === 'stopped' && it.branch && 'branch kept', `${it.sessions} session${it.sessions === 1 ? '' : 's'}`].filter(Boolean).join(' · ')}</span>
            ${it.flags.length > 0 && html`<span class="cleanup-warn">${`Unsaved work: ${it.flags.join(', ')}${picked.has(it.key) ? ' — will be discarded' : ''}`}</span>`}
            ${failed[it.key] && html`<span role="alert" class="error">${failed[it.key]}</span>`}
          </li>`)}</ul>`}
        <div class="cleanup-actions">
          <button type="button" class="btn" onClick=${onClose}>Cancel</button>
          <button type="button" class="btn btn--danger" disabled=${busy || n === 0} onClick=${this.confirm}>${busy ? 'Cleaning…' : `Clean up ${n}`}</button>
        </div>
      </div>
    </div>`;
  }
}
