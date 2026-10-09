import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { mdToHtml } from './run.js';
import { PeekLink } from './peek.js';
import { shortRepo } from './fmt.js';

const html = htm.bind(h);

// ---- pure helpers (unit-tested in test_ui_static.py) -------------------------------------------

// "2h", "3d": how long ago a flow was touched, for the switcher.
export function ago(epochSec, nowMs = Date.now()) {
  const s = Math.max(0, Math.round(nowMs / 1000 - epochSec));
  if (s < 60) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

// An issue row's four-segment track: created, fact-checked, checked or fixed, done.
// `on` segments are complete; `now` is the segment in progress and its tone.
export function issueTrack(state, sessionDone) {
  const t = {
    creating: { on: 0, now: 0, tone: 'live', label: 'creating…' },
    created: { on: 1, now: sessionDone ? null : 1, tone: 'live', label: 'created' },
    checking: { on: 1, now: 1, tone: 'live', label: 'fact-checking…' },
    checked: { on: 3, now: null, label: 'checked' },
    fixing: { on: 2, now: 2, tone: 'warn', label: 'fixing…' },
    fixed: { on: 3, now: null, label: 'fixed' },
    failed: { on: 0, now: 0, tone: 'error', label: 'failed' },
  }[state] || { on: 0, now: null, label: state };
  // Once the session ends every issue it made is done; only a failed create stays failed.
  if (!sessionDone || state === 'failed') return t;
  return { on: 4, now: null, label: ['checked', 'fixed'].includes(state) ? state : 'done' };
}

// Rows from the session plus any issue in the flow's final list it didn't show (a run made before
// progress was tracked, or a create the stream didn't name).
export function mergeRows(progress, issues) {
  const rows = ((progress && progress.rows) || []).map((r) => ({ ...r }));
  for (const n of issues || []) if (!rows.some((r) => r.number === n)) rows.push({ number: n, title: '', state: 'created' });
  return { reading: progress ? progress.reading && !rows.length : !rows.length, rows };
}

// Frontmatter is metadata for Obsidian, not something to read in the pane.
export const stripFrontmatter = (md) => String(md || '').replace(/^---\n[\s\S]*?\n---\n?/, '');

// ---- note pane -----------------------------------------------------------------------------------

// One vault note, read-only. `path` is vault-relative; `stale` marks a file the running step rewrites.
export class NotePane extends Component {
  state = { note: null, error: null };

  componentDidMount() { this.load(); }

  componentDidUpdate(prev) {
    if (prev.path !== this.props.path || prev.version !== this.props.version) this.load();
  }

  async load() {
    const { path } = this.props;
    try {
      const res = await fetch(`/api/notes?path=${encodeURIComponent(path)}`, { headers: { Accept: 'application/json' } });
      const body = await res.json().catch(() => null);
      if (this.props.path !== path) return;
      this.setState(res.ok ? { note: body, error: null } : { note: null, error: res.status === 404 ? 'missing' : (body && body.error) || 'unreadable' });
    } catch {
      this.setState({ note: null, error: 'unreachable' });
    }
  }

  render({ path, stale }, { note, error }) {
    const name = path.split('/').pop();
    return html`<article class="flow-doc" aria-label=${name}>
      <div class="flow-doc-head">
        <div>
          <h2>${name}${stale && html` <span class="flow-tag">Being rewritten</span>`}</h2>
          <p class="mono">${path}</p>
        </div>
        ${note && html`<a class="btn" href=${note.url}>Open in Obsidian</a>`}
      </div>
      ${note && html`<div class="md flow-doc-body" dangerouslySetInnerHTML=${{ __html: mdToHtml(stripFrontmatter(note.text)) }}></div>`}
      ${error === 'missing' && html`<p class="note">${name} isn't in this folder yet. If the step wrote it elsewhere, correct the folder in the next step.</p>`}
      ${error === 'unreachable' && html`<p class="note">Could not reach the aiw server to read this note.</p>`}
      ${error && !['missing', 'unreachable'].includes(error) && html`<p class="note">${error}. Check the notes vault folder in <a href="#/settings">Settings</a>.</p>`}
      ${!note && !error && html`<p class="note" role="status">Loading ${name}…</p>`}
    </article>`;
  }
}

// ---- issue rows ----------------------------------------------------------------------------------

export function IssueRows({ title, progress, slug, sessionDone }) {
  const [owner, repo] = String(slug || '').split('/');
  const rows = (progress && progress.rows) || [];
  return html`<section class="flow-doc" aria-labelledby="flow-fi-h">
    <div class="flow-doc-head"><div><h2 id="flow-fi-h">Issues for ${title}</h2></div></div>
    <ol class="fi-rows">
      <li class="fi-row fi-reading">
        <span class="fi-num" aria-hidden="true">${progress && !progress.reading ? '✓' : '·'}</span>
        <span class="fi-title">Reading the PRD</span>
        <span class="fi-state">${progress && !progress.reading ? 'done' : 'reading…'}</span>
      </li>
      ${rows.map((r, i) => {
        const t = issueTrack(r.state, sessionDone);
        const num = r.number && owner && repo
          ? html`<${PeekLink} kind="issue" owner=${owner} repo=${repo} n=${r.number} href=${`https://github.com/${owner}/${repo}/issues/${r.number}`}>#${r.number}</${PeekLink}>`
          : html`<span>${r.number ? `#${r.number}` : '—'}</span>`;
        return html`<li class="fi-row" key=${i} aria-label=${`${r.number ? `Issue ${r.number}` : 'New issue'}, ${t.label}`}>
          <span class="fi-num">${num}</span>
          <span class="fi-title">${r.title || 'Untitled issue'}</span>
          <span class="fi-track" aria-hidden="true">${[0, 1, 2, 3].map((k) => html`<i class=${k < t.on ? 'on' : k === t.now ? `now ${t.tone}` : ''}></i>`)}</span>
          <span class=${`fi-state ${t.tone || ''}`}>${t.label}</span>
        </li>`;
      })}
    </ol>
    ${progress && !progress.reading && !rows.length && html`<p class="note">No issues created yet.</p>`}
  </section>`;
}

// ---- flows switcher ------------------------------------------------------------------------------

const STEP_LABEL = { dump: 'Dump', prd: 'PRD', issues: 'Issues', dispatch: 'Dispatch' };

export class FlowSwitcher extends Component {
  state = { open: false, flows: null, archived: false, active: 0 };

  async load(archived = this.state.archived) {
    try {
      const res = await fetch(`/api/flows${archived ? '?archived=1' : ''}`, { headers: { Accept: 'application/json' } });
      const body = res.ok ? await res.json() : null;
      this.setState({ flows: (body && body.flows) || [], archived });
    } catch {
      this.setState({ flows: [] });
    }
  }

  toggle = () => {
    const open = !this.state.open;
    this.setState({ open, active: 0 });
    if (open) this.load();
  };

  close = () => this.setState({ open: false });

  archive = async (f, e) => {
    e.preventDefault();
    e.stopPropagation();
    await fetch(`/api/flows/${encodeURIComponent(f.id)}/${f.archived ? 'unarchive' : 'archive'}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => null);
    globalThis.dispatchEvent(new Event('aiw:flow'));
    this.load();
  };

  key = (e) => {
    const n = (this.state.flows || []).length;
    if (e.key === 'Escape') { e.preventDefault(); this.close(); this.btn && this.btn.focus(); }
    else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && n) {
      e.preventDefault();
      const active = (this.state.active + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
      this.setState({ active });
      const a = this.base && this.base.querySelectorAll('.fs-row > a')[active];
      if (a) a.focus();
    }
  };

  render({ current }, { open, flows, archived }) {
    return html`<div class="fs" onKeyDown=${this.key}>
      <button type="button" class="btn" aria-expanded=${open ? 'true' : 'false'} aria-controls="fs-list" ref=${(b) => { this.btn = b; }} onClick=${this.toggle}>Flows</button>
      ${open && html`<div class="fs-pop" id="fs-list" role="dialog" aria-label="Previous flows">
        ${flows === null && html`<p class="note" role="status">Loading flows…</p>`}
        ${flows && !flows.length && html`<p class="note">${archived ? 'No flows yet.' : 'No flows yet. Type an idea into Dump to start one.'}</p>`}
        ${flows && flows.length > 0 && html`<ul class="fs-rows">
          ${flows.map((f) => html`<li class=${`fs-row${f.id === current ? ' current' : ''}${f.archived ? ' archived' : ''}`} key=${f.id}>
            <a href=${`#/flow/${encodeURIComponent(f.id)}`} aria-current=${f.id === current ? 'true' : undefined} onClick=${this.close}>
              <span class="fs-name">${f.name}</span>
              <span class="fs-meta"><span>${f.dispatched ? 'Dispatched' : STEP_LABEL[f.step]}</span><time>${ago(f.updated)}</time></span>
              <span class="fs-repo mono">${shortRepo(f.repo)}</span>
            </a>
            <button type="button" class="fs-archive" onClick=${(e) => this.archive(f, e)}>${f.archived ? 'Restore' : 'Archive'}</button>
          </li>`)}
        </ul>`}
        <label class="check fs-show"><input type="checkbox" checked=${archived} onChange=${(e) => this.load(e.target.checked)} /> Show archived</label>
      </div>`}
    </div>`;
  }
}
