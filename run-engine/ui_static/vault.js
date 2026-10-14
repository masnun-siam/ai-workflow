import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { toast } from './toast.js';

const html = htm.bind(h);

// No repo yet: a new idea runs in the notes vault and files under 05-Work/<Project>/<Feature>.
// FolderChooser suggests that folder as you type (keywords, instant) or on request (Claude), and
// CreateRepoDialog turns an approved idea into a local git repo.

export const NO_REPO_COMMANDS = new Set(['create-prd', 'dump', 'intake']); // and the custom prompt

let listing = null;
export function loadVaultFolders() {
  listing = listing || fetch('/api/vault/folders', { headers: { Accept: 'application/json' } })
    .then((r) => (r.ok ? r.json() : { folders: [] }))
    .then((b) => (Array.isArray(b.folders) ? b.folders : []))
    .catch(() => { listing = null; return []; });
  return listing;
}

const STOP = new Set('the and for with from that this into have will should would could about when what which there their them they then than your our new add make build want need idea app feature page using also just like more some each only into over under'.split(' '));
export const words = (s) => [...new Set(String(s || '').toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 2 && !STOP.has(w)))];

// Existing folders ranked by how many of the text's words their project and feature names share:
// [{ project, feature, score }], best first, at most `n`. Feature folders beat their bare project.
export function keywordSuggest(folders, text, n = 3) {
  const want = words(text);
  if (!want.length) return [];
  // A word also matches its near forms (member/members, remind/reminder), not any shared prefix.
  const near = (a, b) => a.startsWith(b) && a.length - b.length <= 2;
  const hits = (names) => want.filter((w) => names.some((x) => x === w || near(x, w) || near(w, x))).length;
  const scored = folders.map((f) => {
    // Naming the project is the strongest signal, so its words count double.
    // A feature folder only wins over its project when one of its own words matched.
    const feat = hits(words(f.feature || ''));
    if (f.feature && !feat) return { project: f.project, feature: f.feature, score: 0 };
    return { project: f.project, feature: f.feature, score: 2 * hits(words(f.project)) + feat + (feat ? 0.5 : 0) };
  });
  return scored.filter((s) => s.score >= 1).sort((a, b) => b.score - a.score).slice(0, n);
}

// The folder a choice stands for, or null when no project is named.
export function folderOf({ project, feature } = {}) {
  const p = String(project || '').trim().replace(/[/\\]/g, ' ');
  const f = String(feature || '').trim().replace(/[/\\]/g, ' ');
  if (!p || p.startsWith('.') || f.startsWith('.')) return null;
  return f ? `05-Work/${p}/${f}` : `05-Work/${p}`;
}

export class FolderChooser extends Component {
  state = { folders: [], asking: false, why: '', error: '' };

  componentDidMount() {
    loadVaultFolders().then((folders) => !this.gone && this.setState({ folders }));
  }

  componentWillUnmount() {
    this.gone = true;
  }

  // While the user has not typed a folder themselves, follow the best keyword match.
  componentDidUpdate(prev) {
    const { text, value, onChange } = this.props;
    if (value.touched || prev.text === text) return;
    const top = keywordSuggest(this.state.folders, text)[0];
    const next = top ? { project: top.project, feature: top.feature || '' } : { project: '', feature: '' };
    if (next.project !== value.project || next.feature !== value.feature) onChange({ ...next, touched: false });
  }

  ask = async () => {
    this.setState({ asking: true, error: '', why: '' });
    try {
      const res = await fetch('/api/vault/suggest', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: this.props.text }) });
      const b = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(b.error || `HTTP ${res.status}`);
      this.props.onChange({ project: b.project, feature: b.feature, touched: true });
      this.setState({ why: b.why || '' });
    } catch (e) {
      this.setState({ error: `Claude could not suggest one: ${e.message}` });
    } finally {
      if (!this.gone) this.setState({ asking: false });
    }
  };

  render({ id, text, value, onChange }, { folders, asking, why, error }) {
    const projects = [...new Set(folders.map((f) => f.project))];
    const features = folders.filter((f) => f.project === value.project && f.feature).map((f) => f.feature);
    const newProject = value.project && !projects.includes(value.project);
    const newFeature = value.feature && !newProject && !features.includes(value.feature);
    const picks = keywordSuggest(folders, text);
    const set = (k) => (e) => onChange({ ...value, [k]: e.target.value, touched: true });
    const where = folderOf(value);
    return html`<fieldset class="vf">
      <legend>Vault folder <span class="muted">where this idea is filed; the session confirms it with you first</span></legend>
      <div class="vf-row">
        <label for=${`${id}-project`}>Project <input id=${`${id}-project`} type="text" list=${`${id}-projects`} value=${value.project} onInput=${set('project')} placeholder="e.g. Gym App" autocomplete="off" /></label>
        <label for=${`${id}-feature`}>Feature <input id=${`${id}-feature`} type="text" list=${`${id}-features`} value=${value.feature} onInput=${set('feature')} placeholder="e.g. Member check-ins" autocomplete="off" /></label>
        <datalist id=${`${id}-projects`}>${projects.map((p) => html`<option value=${p} />`)}</datalist>
        <datalist id=${`${id}-features`}>${features.map((f) => html`<option value=${f} />`)}</datalist>
      </div>
      <div class="vf-meta">
        ${where ? html`<span class="mono">${where}</span>` : html`<span class="muted">No folder yet: the session picks one with you.</span>`}
        ${newProject && html`<span class="chip">new project</span>`}
        ${newFeature && html`<span class="chip">new feature</span>`}
        <span class="spacer"></span>
        <button type="button" class="linkish" disabled=${asking || !String(text || '').trim()} onClick=${this.ask}
          title=${String(text || '').trim() ? 'A quick Haiku call reads your text and the 05-Work folders' : 'Describe the idea first'}>${asking ? 'Asking Claude…' : 'Suggest with Claude'}</button>
      </div>
      ${picks.length > 0 && html`<div class="vf-picks" role="group" aria-label="Matching folders">
        <span class="muted">Matches:</span>
        ${picks.map((p) => html`<button type="button" class="fchip" onClick=${() => onChange({ project: p.project, feature: p.feature || '', touched: true })}>${p.project}${p.feature ? ` / ${p.feature}` : ''}</button>`)}
      </div>`}
      ${why && html`<p class="note">Claude: ${why}</p>`}
      ${error && html`<p role="alert" class="error">${error}</p>`}
    </fieldset>`;
  }
}

// Turns an idea into a code repo: a folder picked with the macOS dialog, git init, a README and,
// given a vault PRD, docs/prds/<slug>.md. Registered as local/<name> until it has a GitHub remote.
// Folders the registered repos live in, most used first: likely homes for a new one.
export function parentFolders(repos, n = 5) {
  const count = new Map();
  for (const r of repos || []) {
    const dir = String(r.path || '').replace(/\/+$/, '').replace(/\/[^/]+$/, '');
    if (dir.startsWith('/')) count.set(dir, (count.get(dir) || 0) + 1);
  }
  return [...count].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, n).map(([d]) => d);
}

export const repoName = (s) => String(s || '').trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 100);

export class CreateRepoDialog extends Component {
  state = { name: repoName(this.props.name), parent: '', prdFolder: this.props.prdFolder || '', prd: null, busy: false, error: '' };

  componentDidMount() {
    this.opener = document.activeElement; // focus goes back here on close
    this.checkPrd();
    // The folder dialog opens on the Mac's own screen, so a tailnet browser types the folder instead;
    // the folders existing repos live in are offered either way.
    fetch('/api/repos', { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => b && this.setState({ canBrowse: b.can_browse === true, homes: parentFolders(b.repos) }))
      .catch(() => {});
    setTimeout(() => this.root && this.root.querySelector('#cr-name')?.focus(), 0);
  }

  componentWillUnmount() {
    if (this.opener && this.opener.isConnected) this.opener.focus();
  }

  // Esc closes this dialog only: the page's own Esc (go back) must not see it.
  keys = (e) => {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    e.stopPropagation();
    this.props.onClose();
  };

  // The PRD folder's status, for the folder as typed now: {exists, status, title, folder} or null.
  checkPrd = async () => {
    const folder = this.state.prdFolder.trim();
    if (!folder) {
      this.setState({ prd: null });
      return null;
    }
    try {
      const r = await fetch(`/api/vault/prd?folder=${encodeURIComponent(folder)}`, { headers: { Accept: 'application/json' } });
      const prd = r.ok ? await r.json() : { exists: false, folder };
      this.setState({ prd });
      return prd;
    } catch {
      this.setState({ prd: null });
      return null;
    }
  };

  pickParent = async () => {
    try {
      const r = await fetch('/api/repos/browse', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ start: this.state.parent }) });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.error || `HTTP ${r.status}`);
      if (b.path) this.setState({ parent: b.path, error: '' });
    } catch (e) {
      this.setState({ error: `Could not open the folder picker: ${e.message}` });
    }
  };

  create = async (e) => {
    e.preventDefault();
    const { name, parent, prdFolder } = this.state;
    if (!name || !parent) return this.setState({ error: !name ? 'Name the repo' : 'Choose the folder to create it in' });
    // Check the folder as typed now, not a status fetched for an earlier value.
    const prd = prdFolder && (this.state.prd?.folder === prdFolder.trim() ? this.state.prd : await this.checkPrd());
    if (prdFolder && !(prd && prd.exists)) return this.setState({ error: 'No PRD.md in that vault folder' });
    this.setState({ busy: true, error: '' });
    try {
      const r = await fetch('/api/repos/create', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ parent, name, ...(prdFolder ? { prd_folder: prdFolder } : {}) }) });
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(b.error || `HTTP ${r.status}`);
      toast(`Created ${b.slug}`);
      this.props.onDone(b);
    } catch (err) {
      this.setState({ busy: false, error: err.message });
    }
  };

  render({ onClose, withPrd }, { name, parent, prdFolder, prd, busy, error }) {
    return html`<div class="overlay" ref=${(el) => { this.root = el; }} onKeyDown=${this.keys} onMouseDown=${(e) => e.target === e.currentTarget && onClose()}>
      <form class="dialog create-repo" role="dialog" aria-modal="true" aria-labelledby="cr-h" onSubmit=${this.create}>
        <h2 id="cr-h">Create a repo</h2>
        <p class="muted">Makes a local git repo with a README${withPrd ? ' and the PRD in docs/prds/' : ''} and adds it to your repos as ${'local/<name>'}. Nothing is committed or pushed; once you add a GitHub remote, aiw picks up its real name.</p>
        <label for="cr-name">Name</label>
        <input id="cr-name" type="text" class="field" value=${name} autocomplete="off" onInput=${(e) => this.setState({ name: repoName(e.target.value) })} placeholder="gym-app" />
        <label for="cr-parent">Create it in</label>
        <div class="repo-row">
          <input id="cr-parent" type="text" class="field" value=${parent} autocomplete="off" spellcheck="false" placeholder="/Users/you/Projects or ~/Projects"
            onInput=${(e) => this.setState({ parent: e.target.value, error: '' })} />
          ${this.state.canBrowse && html`<button type="button" class="btn" onClick=${this.pickParent}>Choose…</button>`}
        </div>
        ${(this.state.homes || []).length > 0 && html`<div class="vf-picks" role="group" aria-label="Where your repos live">
          <span class="muted">Where your repos live:</span>
          ${this.state.homes.map((d) => html`<button type="button" class="fchip" aria-pressed=${parent === d ? 'true' : 'false'} onClick=${() => this.setState({ parent: d, error: '' })}>${d.replace(/^\/Users\/[^/]+/, '~')}</button>`)}
        </div>`}
        ${parent && name && html`<p class="note mono">${parent.trim().replace(/\/+$/, '')}/${name}</p>`}
        ${withPrd && html`<label for="cr-prd">PRD from the vault folder</label>
          <input id="cr-prd" type="text" class="field" value=${prdFolder} onInput=${(e) => this.setState({ prdFolder: e.target.value, prd: null })} onBlur=${this.checkPrd} placeholder="05-Work/<Project>/<Feature>" />
          ${prd && (prd.exists
            ? html`<p class="note">${prd.title || 'PRD'} · <span class=${prd.status === 'Approved' ? 'chip chip-done' : 'chip chip-waiting'}>${prd.status || 'no status'}</span>${prd.status !== 'Approved' ? ' The PRD is not approved yet; you can still create the repo.' : ''}</p>`
            : html`<p class="note error">No PRD.md in that folder.</p>`)}`}
        ${error && html`<p role="alert" class="error">${error}</p>`}
        <div class="cleanup-actions">
          <button type="button" class="btn" onClick=${onClose}>Cancel</button>
          <button type="submit" class="btn btn--primary" disabled=${busy}>${busy ? 'Creating…' : 'Create repo'}</button>
        </div>
      </form>
    </div>`;
  }
}

// On a finished no-repo create-prd session: the PRD's state and, once it is approved, Create repo.
export const ideaPrdSession = (meta) => !!meta && meta.no_repo === true && /^\/(?:[\w-]+:)?create-prd\b/.test(meta.command || '') && meta.outcome === 'done';

export class NewIdeaPanel extends Component {
  state = { prd: null, creating: false, made: null };

  componentDidMount() {
    this.load();
  }

  load = () => {
    const folder = this.props.meta.vault_folder;
    if (!folder) return;
    this.setState({ prd: null });
    fetch(`/api/vault/prd?folder=${encodeURIComponent(folder)}`, { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : { error: true }))
      .then((prd) => !this.gone && this.setState({ prd }))
      .catch(() => !this.gone && this.setState({ prd: { error: true } }));
  };

  componentWillUnmount() {
    this.gone = true;
  }

  render({ meta }, { prd, creating, made }) {
    const folder = meta.vault_folder || '';
    const approved = prd && prd.exists && prd.status === 'Approved';
    return html`<section class="panel idea-panel" aria-label="New idea">
      <h2>New idea · no repo yet</h2>
      ${made ? html`<p>Created <b class="mono">${made.slug}</b> at <span class="mono">${made.path}</span>. It's in your repos now; start a run there from <a href="#/new">New run</a>.</p>`
        : !folder ? html`<p class="muted">This session ran without a suggested vault folder. Create the repo once its PRD is approved, and name the PRD's folder in the dialog.</p>`
        : !prd ? html`<p class="muted">Checking the PRD in <span class="mono">${folder}</span>…</p>`
        : prd.error ? html`<p class="error">Could not read the PRD in <span class="mono">${folder}</span>. <button type="button" class="linkish" onClick=${this.load}>Retry</button></p>`
        : !prd.exists ? html`<p class="muted">No PRD.md in <span class="mono">${folder}</span> yet. If the session filed it elsewhere, name that folder in the dialog.</p>`
        : approved ? html`<p>The PRD <b>${prd.title}</b> is approved. Make its code repo: a local git repo with the PRD in docs/prds/ and a README.</p>`
        : html`<p class="muted">The PRD <b>${prd.title}</b> is ${prd.status || 'not approved'}. Once it's approved, create its repo here.</p>`}
      ${!made && html`<button type="button" class=${approved ? 'btn btn--primary' : 'btn'} onClick=${() => this.setState({ creating: true })}>Create repo…</button>`}
      ${creating && html`<${CreateRepoDialog} withPrd=${true} prdFolder=${folder} name=${(prd && prd.title) || folder.split('/').pop()}
        onClose=${() => this.setState({ creating: false })} onDone=${(m) => this.setState({ creating: false, made: m })} />`}
    </section>`;
  }
}
