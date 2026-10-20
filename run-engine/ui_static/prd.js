import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { sendJson } from './fmt.js';
import { mdToHtml } from './md.js';
import { Md } from './peek.js';

const html = htm.bind(h);

// Any view opens a PRD drawer by event, like the issue and PR drawers (App renders it).
export const openPrd = (repo, path, title) => globalThis.dispatchEvent(new CustomEvent('aiw:peek', { detail: { kind: 'prd', repo, path, title } }));

// Ask Claude: /create-prd on the existing file updates it (the skill reads it first and keeps it consistent).
export const askBody = (repo, path, text) => ({ repo, command: 'create-prd', args: `${path} ${text.trim()}` });

// Unsaved edits, read by the App before Esc closes the drawer.
export const prdEdits = { dirty: false };

export const savedText = (r) => (r.committed ? `Committed ${r.commit} on ${r.branch} (not pushed)` : 'No changes to save');

// PRD drawer: Read (rendered), Edit (raw markdown, commits only this file), Ask Claude (a create-prd session).
export class PrdDialog extends Component {
  state = { tab: 'read', data: null, error: '', draft: '', ask: '', busy: false, note: '', session: '' };

  componentDidMount() {
    this.load();
  }

  componentWillUnmount() {
    this.gone = true;
    prdEdits.dirty = false;
  }

  load = async () => {
    const { repo, path } = this.props;
    this.setState({ error: '' });
    try {
      const res = await fetch(`/api/prd?repo=${encodeURIComponent(repo)}&path=${encodeURIComponent(path)}`, { headers: { Accept: 'application/json' } });
      const data = await res.json().catch(() => ({}));
      if (this.gone) return;
      if (!res.ok) this.setState({ error: data.error || `HTTP ${res.status}` });
      else this.setState({ data, draft: data.text });
    } catch {
      if (!this.gone) this.setState({ error: 'Could not reach the aiw server' });
    }
  };

  save = async () => {
    const { repo, path } = this.props;
    this.setState({ busy: true, error: '', note: '' });
    const r = await sendJson('POST', '/api/prd', { repo, path, text: this.state.draft });
    if (this.gone) return;
    this.setState({ busy: false, error: r.ok ? '' : r.error, note: r.ok ? savedText(r.data) : '' });
    if (r.ok) this.setState(({ data, draft }) => ({ data: { ...data, text: draft } }));
  };

  askClaude = async () => {
    const { repo, path } = this.props;
    this.setState({ busy: true, error: '', note: '' });
    const r = await sendJson('POST', '/api/sessions', askBody(repo, path, this.state.ask));
    if (this.gone) return;
    this.setState({ busy: false, error: r.ok ? '' : r.error, session: r.ok ? r.data.id : '', ask: r.ok ? '' : this.state.ask });
  };

  render({ repo, path, title, onClose }, { tab, data, error, draft, ask, busy, note, session }) {
    const dirty = !!data && draft !== data.text;
    prdEdits.dirty = dirty;
    return html`<div class="overlay" onMouseDown=${(e) => e.target === e.currentTarget && onClose()}>
      <div class="dialog issue wide" role="dialog" aria-modal="true" aria-labelledby="iss-title">
        <div class="iss-head"><div class="iss-ref mono">${repo} · ${path}</div>${data && html`<span class="iss-state">${data.branch}</span>`}</div>
        <h2 id="iss-title" class="iss-title">${title || path}</h2>
        <div class="pk-tabs" role="tablist" aria-label="PRD">
          ${[['read', 'Read'], ['edit', dirty ? 'Edit •' : 'Edit'], ['ask', 'Ask Claude']].map(([k, label]) => html`<button type="button" role="tab" aria-selected=${tab === k} onClick=${() => this.setState({ tab: k, note: '' })}>${label}</button>`)}
        </div>
        <div class="iss-scroll" role="tabpanel" tabindex="0">
          ${!data && !error && html`<p role="status" class="muted">Loading…</p>`}
          ${data && tab === 'read' && html`<${Md} htmlText=${mdToHtml(data.text)} />`}
          ${data && tab === 'edit' && html`<label class="sr-only" for="prd-text">PRD markdown</label>
            <textarea id="prd-text" class="field prd-edit" spellcheck="false" value=${draft} onInput=${(e) => this.setState({ draft: e.target.value })}></textarea>
            <p class="note">Save commits only this file on <code>${data.branch}</code>. It is not pushed.</p>`}
          ${data && tab === 'ask' && html`<label for="prd-ask">What should change?</label>
            <textarea id="prd-ask" class="field" rows="5" placeholder="e.g. Admins can also export the list as CSV" value=${ask} onInput=${(e) => this.setState({ ask: e.target.value })}></textarea>
            <p class="note">Starts <code>/create-prd ${path}</code> with this request. It updates the PRD, adds a change-log line and asks you anything it can't settle.</p>
            ${session && html`<p role="status">Started. <a href=${`#/session/${encodeURIComponent(session)}`} onClick=${onClose}>Open the session</a></p>`}`}
          ${error && html`<p role="alert" class="error">${error}</p>`}
        </div>
        <div class="iss-foot">
          ${tab === 'edit' && data && html`<button type="button" class="btn btn--primary" disabled=${busy || !dirty} onClick=${this.save}>${busy ? 'Saving…' : 'Save and commit'}</button>
            <button type="button" class="btn" disabled=${busy || !dirty} onClick=${() => this.setState({ draft: data.text })}>Discard</button>`}
          ${tab === 'ask' && data && html`<button type="button" class="btn btn--primary" disabled=${busy || !ask.trim()} onClick=${this.askClaude}>${busy ? 'Starting…' : 'Start'}</button>`}
          ${note && html`<span role="status" class="muted">${note}</span>`}
          <span class="spacer"></span>
          <button type="button" class="btn" onClick=${() => (!dirty || !globalThis.confirm || globalThis.confirm('Discard your unsaved edits?')) && onClose()}>Close <kbd>Esc</kbd></button>
        </div>
      </div>
    </div>`;
  }
}
