import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { toast } from './toast.js';

const html = htm.bind(h);

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

export const repoRow = (cfg, slug) => ({ auto_grind: false, autopilot_cap: 2, slack_channel: '', ...((cfg || {})[slug] || {}) });

// One repo's row. Plain function so tests can walk the tree.
export function repoSection(slug, row, err, save) {
  const id = slug.replace(/\W/g, '-');
  return html`<div class="settings-repo" key=${slug}>
    <span class="repo-slug">${slug}</span>
    <label class="check"><input type="checkbox" aria-label=${`Auto-grind ${slug}`} checked=${row.auto_grind} onChange=${(e) => save(slug, { auto_grind: e.target.checked })} /> Auto-grind</label>
    <label for=${`cap-${id}`}>Autopilot cap</label>
    <input id=${`cap-${id}`} type="number" min="1" max="5" step="1" aria-label=${`Autopilot cap ${slug}`} value=${row.autopilot_cap} onChange=${(e) => save(slug, { autopilot_cap: Number(e.target.value) })} />
    <label for=${`slack-${id}`}>Slack channel</label>
    <input id=${`slack-${id}`} type="text" class="field" aria-label=${`Slack channel ${slug}`} placeholder="#reviews" value=${row.slack_channel} onChange=${(e) => save(slug, { slack_channel: e.target.value.trim() })} />
    ${err && html`<p role="alert" class="error">${err}</p>`}
  </div>`;
}

// Per-repo rows: a search narrows them; without one only the first few show until "Show all".
export const REPO_PREVIEW = 8;
export function visibleRepos(repos, q, all) {
  const n = q.trim().toLowerCase();
  const hit = n ? repos.filter((r) => `${r.slug} ${r.path || ''}`.toLowerCase().includes(n)) : repos;
  return n || all ? hit : hit.slice(0, REPO_PREVIEW);
}

// Only the fields the user touched go out; an empty secret box means "keep the stored one".
export function notifyBody(form) {
  const body = { server: form.server, topic: form.topic, user: form.user, public_url: form.public_url };
  for (const k of ['token', 'password']) {
    if (form[`clear_${k}`]) body[k] = '';
    else if (form[k]) body[k] = form[k];
  }
  return body;
}

class NotifyPanel extends Component {
  state = { form: null, msg: '', busy: false };

  async componentDidMount() {
    try { this.setState({ form: { ...(await api('GET', '/api/settings/notify')), token: '', password: '' } }); } catch (e) { this.setState({ msg: e.message }); }
  }

  set = (k) => (e) => this.setState(({ form }) => ({ form: { ...form, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value } }));

  save = async (e) => {
    e.preventDefault();
    this.setState({ busy: true, msg: '' });
    try {
      const r = await api('POST', '/api/settings/notify', notifyBody(this.state.form));
      this.setState({ form: { ...r, token: '', password: '' } });
      toast('Notifications saved');
    } catch (er) { this.setState({ msg: er.message }); }
    this.setState({ busy: false });
  };

  render(_, { form, msg, busy }) {
    const field = (k, label, type = 'text', ph = '') => html`<label for=${`ntfy-${k}`}>${label}</label>
      <input id=${`ntfy-${k}`} type=${type} class="field" autocomplete="off" spellcheck="false" placeholder=${ph} value=${form[k]} onInput=${this.set(k)} />`;
    const secret = (k, label) => html`${field(k, label, 'password', form[`${k}_set`] ? 'Set (leave empty to keep)' : 'Not set')}
      ${form[`${k}_set`] && html`<label class="check"><input type="checkbox" checked=${!!form[`clear_${k}`]} onChange=${this.set(`clear_${k}`)} /> Remove the saved ${label.toLowerCase()}</label>`}`;
    return html`<form class="panel" aria-labelledby="ntfy-h" onSubmit=${this.save} noValidate>
      <h2 id="ntfy-h">Notifications</h2>
      <p class="note">Push a phone notification through <a href="https://ntfy.sh" target="_blank" rel="noopener noreferrer">ntfy</a> when a session waits on you, finishes or fails. Saved to <code>ui.json</code> (mode 0600); a token or password never comes back to the browser.</p>
      ${!form && !msg && html`<p role="status" class="muted">Loading…</p>`}
      ${form && html`${form.env.length > 0 && html`<p class="note">Set by environment, which wins over this form: ${form.env.join(', ')}.</p>`}
        ${field('server', 'Server', 'url', 'https://ntfy.sh')}
        ${field('topic', 'Topic')}
        ${secret('token', 'Token')}
        ${field('user', 'User (instead of a token)')}
        ${secret('password', 'Password')}
        ${field('public_url', 'Public URL of this UI (notification links open it)', 'url', 'https://mac.tailnet.ts.net')}
        <div class="launch-actions"><button type="submit" disabled=${busy}>${busy ? 'Saving…' : 'Save notifications'}</button></div>`}
      ${msg && html`<p role="alert" class="error">${msg}</p>`}
    </form>`;
  }
}

class ReviewPanel extends Component {
  state = { cfg: null, msg: '', busy: false };

  async componentDidMount() {
    try { this.setState({ cfg: await api('GET', '/api/settings/review') }); } catch (e) { this.setState({ msg: e.message }); }
  }

  patch = (p) => this.setState(({ cfg }) => ({ cfg: { ...cfg, ...p } }));

  send = async (body, done) => {
    this.setState({ busy: true, msg: '' });
    try { this.setState({ cfg: await api('POST', '/api/settings/review', body) }); toast(done); } catch (er) { this.setState({ msg: er.message }); }
    this.setState({ busy: false });
  };

  render(_, { cfg, msg, busy }) {
    if (!cfg) return html`<section class="panel"><h2>Peer review</h2>${msg ? html`<p role="alert" class="error">${msg}</p>` : html`<p class="muted" role="status">Loading…</p>`}</section>`;
    const names = Object.keys(cfg.lenses);
    return html`<form class="panel" aria-labelledby="pr-h" onSubmit=${(e) => { e.preventDefault(); this.send({ max_rounds: Number(cfg.max_rounds), default_lenses: cfg.default_lenses, lenses: cfg.lenses }, 'Peer review saved'); }} noValidate>
      <h2 id="pr-h">Peer review</h2>
      <p class="note">How a review panel runs. Your changes are kept apart from the plugin's defaults, so an update still brings new defaults for anything you didn't change.</p>
      <label for="pr-rounds">Rounds before a panel stops (1 to 10)</label>
      <input id="pr-rounds" type="number" min="1" max="10" step="1" value=${cfg.max_rounds} onInput=${(e) => this.patch({ max_rounds: e.target.value })} />
      <fieldset class="lens-picks"><legend>Ticked by default</legend>
        ${names.map((n) => html`<label class="check"><input type="checkbox" checked=${cfg.default_lenses.includes(n)}
          onChange=${(e) => this.patch({ default_lenses: e.target.checked ? [...cfg.default_lenses, n] : cfg.default_lenses.filter((x) => x !== n) })} /> ${n}</label>`)}
      </fieldset>
      ${names.map((n) => html`<details class="lens-prompt"><summary>${n} prompt${cfg.lenses[n] !== cfg.shipped.lenses[n] ? ' (edited)' : ''}</summary>
        <textarea class="field" rows="6" aria-label=${`${n} prompt`} value=${cfg.lenses[n]} onInput=${(e) => this.patch({ lenses: { ...cfg.lenses, [n]: e.target.value } })}></textarea></details>`)}
      <div class="launch-actions">
        <button type="submit" disabled=${busy}>${busy ? 'Saving…' : 'Save peer review'}</button>
        ${cfg.overridden && html`<button type="button" disabled=${busy} onClick=${() => globalThis.confirm('Go back to the plugin defaults for peer review?') && this.send({ reset: true }, 'Peer review reset')}>Reset to defaults</button>`}
      </div>
      ${msg && html`<p role="alert" class="error">${msg}</p>`}
    </form>`;
  }
}

// Sections of the page, in nav order. Anything else (or none) is Commands.
export const SECTIONS = [['commands', 'Commands'], ['repos', 'Repos'], ['notifications', 'Notifications'], ['review', 'Peer review'], ['vault', 'Vault']];
export const sectionOf = (s) => (SECTIONS.some(([k]) => k === s) ? s : 'commands');

export class Settings extends Component {
  saved = { commands: [], default: null };
  state = { commands: null, def: '', cfg: {}, rowErr: {}, tests: {}, err: '', saving: false, repos: [], roots: '', scanning: false, scanMsg: '', vault: '', vaultMsg: '', repoQ: '', allRepos: false, problems: null, checking: false };

  async componentDidMount() {
    try {
      const s = await api('GET', '/api/settings');
      this.saved = { commands: s.commands, default: s.default };
      this.setState({ commands: s.commands, def: s.default || '', cfg: s.repos || {}, vault: s.vault_dir || '' });
    } catch (e) {
      this.setState({ commands: [], err: e.message });
    }
    try {
      const r = await api('GET', '/api/repos');
      this.setState({ repos: r.repos || [], roots: (r.scan_roots || []).join('\n') });
    } catch {
      // the Repos panel just stays empty
    }
  }

  scan = async () => {
    this.setState({ scanning: true, scanMsg: '' });
    try {
      const roots = this.state.roots.split('\n').map((s) => s.trim()).filter(Boolean);
      const r = await api('POST', '/api/repos/scan', { roots });
      const n = r.added.length;
      const dup = r.duplicates.length;
      this.setState({ repos: r.repos, scanMsg: n ? `Registered ${n} new repo${n === 1 ? '' : 's'}${dup ? `; ${dup} extra clone${dup === 1 ? '' : 's'} of a known repo skipped` : ''}.` : 'No new repos found.' });
      if (n) toast(`Registered ${n} repo${n === 1 ? '' : 's'}`);
    } catch (e) {
      this.setState({ scanMsg: e.message });
    }
    this.setState({ scanning: false });
  };

  removeRepo = async (slug) => {
    if (!globalThis.confirm(`Unregister ${slug}? Its clone on disk is not touched; Find my repos adds it back.`)) return;
    try {
      const r = await api('POST', '/api/repos/remove', { slug });
      this.setState({ repos: r.repos });
      toast(`Removed ${slug}`);
    } catch (e) {
      this.setState({ scanMsg: e.message });
    }
  };

  checkRepos = async () => {
    this.setState({ checking: true, scanMsg: '' });
    try {
      const { problems } = await api('POST', '/api/repos/check', {});
      const bad = Object.values(problems).filter(Boolean).length;
      this.setState({ problems, scanMsg: bad ? `${bad} repo${bad === 1 ? '' : 's'} with a problem, listed first.` : 'Every remote is reachable.' });
    } catch (e) {
      this.setState({ scanMsg: e.message });
    }
    this.setState({ checking: false });
  };

  // Renaming the default keeps it the default.
  edit = (i, k) => (e) => this.setState(({ commands, def }) => ({
    commands: commands.map((c, j) => (j === i ? { ...c, [k]: e.target.value } : c)),
    def: k === 'label' && def === commands[i].label ? e.target.value : def,
  }));

  add = () => this.setState(({ commands }) => ({ commands: [...commands, { label: '', cmd: '' }] }));

  remove = (i) => this.setState(({ commands, def }) => ({
    commands: commands.filter((_, j) => j !== i),
    def: def === commands[i].label ? commands[0].label : def,
  }));

  test = async (i) => {
    const { cmd } = this.state.commands[i];
    this.setState(({ tests }) => ({ tests: { ...tests, [i]: { msg: 'Testing…' } } }));
    try {
      const r = await api('POST', '/api/settings/test', { cmd });
      this.setState(({ tests }) => ({ tests: { ...tests, [i]: r } }));
    } catch (e) {
      this.setState(({ tests }) => ({ tests: { ...tests, [i]: { ok: false, message: e.message } } }));
    }
  };

  // One repo's row saves on its own and sends only that repo's entry; a rejected save puts the old value back.
  saveRepo = async (slug, patch) => {
    const before = repoRow(this.state.cfg, slug);
    const next = { ...before, ...patch };
    this.setState(({ cfg, rowErr }) => ({ cfg: { ...cfg, [slug]: next }, rowErr: { ...rowErr, [slug]: '' } }));
    try {
      const s = await api('PUT', '/api/settings', { repos: { [slug]: next } });
      this.setState(({ cfg }) => ({ cfg: { ...cfg, [slug]: { ...next, ...((s.repos || {})[slug] || {}) } } }));
      toast(`Saved ${slug}`);
    } catch (er) {
      this.setState(({ cfg, rowErr }) => ({ cfg: { ...cfg, [slug]: before }, rowErr: { ...rowErr, [slug]: er.message } }));
    }
  };

  // The notes vault saves on its own, with the last *saved* commands, like the grinding default.
  saveVault = async (e) => {
    e.preventDefault();
    this.setState({ saving: true, vaultMsg: '' });
    try {
      const s = await api('PUT', '/api/settings', { ...this.saved, vault_dir: this.state.vault });
      this.setState({ vault: s.vault_dir || '' });
      toast('Notes vault saved');
    } catch (er) {
      this.setState({ vaultMsg: er.message });
    }
    this.setState({ saving: false });
  };

  save = async (e) => {
    e.preventDefault();
    const { commands, def } = this.state;
    this.setState({ saving: true, err: '' });
    try {
      const s = await api('PUT', '/api/settings', { commands, default: def || null });
      this.saved = { commands: s.commands, default: s.default };
      this.setState({ commands: s.commands, def: s.default || '' });
      toast('Settings saved');
    } catch (er) {
      this.setState({ err: er.message });
    }
    this.setState({ saving: false });
  };

  render({ section }, { commands, def, cfg, rowErr, tests, err, saving, repos, roots, scanning, scanMsg, vault, vaultMsg, repoQ, allRepos, problems, checking }) {
    const shownRepos = visibleRepos(repos, repoQ, allRepos);
    const listed = problems ? [...repos].sort((a, b) => !!problems[b.slug] - !!problems[a.slug]) : repos;
    if (!commands) return html`<h1>Settings</h1><p role="status">Loading…</p>`;
    const cur = sectionOf(section);
    // Every section stays mounted (hidden, not removed) so unsaved edits survive switching.
    const sec = (k, ...kids) => html`<div class="settings-sec" data-section=${k} hidden=${k !== cur}>${kids}</div>`;
    return html`
      <section class="settings">
        <h1>Settings</h1>
        <div class="settings-layout">
        <nav class="settings-nav" aria-label="Settings sections">
          ${SECTIONS.map(([k, label]) => html`<a href=${`#/settings/${k}`} aria-current=${k === cur ? 'page' : undefined}>${label}</a>`)}
        </nav>
        <div class="settings-main">
          ${sec('commands',
          html`<form class="panel" onSubmit=${this.save} noValidate>
            <h2>Claude commands</h2>
            <p class="note">The command a run is launched with. Add one like <code>cc masum</code> to run under another account. The first row is plain <code>claude</code>: rename it to tell your accounts apart.</p>
            ${commands.map((c, i) => html`
              <div class="cmd-row" key=${i}>
                <input type="text" aria-label="Label" placeholder="Label (Masum)" value=${c.label} onInput=${this.edit(i, 'label')} />
                <input type="text" aria-label="Command" class="mono" placeholder="cc masum" value=${c.cmd} onInput=${this.edit(i, 'cmd')}
                  readOnly=${c.builtin} title=${c.builtin ? 'The built-in command; rename it with the label' : ''} />
                <label class="radio"><input type="radio" name="default" checked=${!!c.label && def === c.label} disabled=${!c.label} onChange=${() => this.setState({ def: c.label })} /> Use by default</label>
                <button type="button" onClick=${() => this.test(i)}>Test</button>
                ${c.builtin
                  ? html`<span class="cmd-builtin muted">Built in</span>`
                  : html`<button type="button" class="btn--danger" aria-label=${`Remove ${c.label || 'command'}`} onClick=${() => this.remove(i)}>Remove</button>`}
                ${tests[i] && html`<span class=${tests[i].ok === false ? 'error' : 'muted'} role="status">${tests[i].message || tests[i].msg}</span>`}
              </div>`)}
            ${err && html`<p role="alert" class="error">${err}</p>`}
            <div class="launch-actions">
              <button type="button" onClick=${this.add}>Add command</button>
              <button type="submit" disabled=${saving}>${saving ? 'Saving…' : 'Save'}</button>
            </div>
          </form>`)}
          ${sec('repos',
          html`<section class="panel" aria-labelledby="grind-h">
            <h2 id="grind-h">Per-repo settings</h2>
            <p class="note">Auto-grind starts a grind when a PR turns ready. The autopilot cap is how many implement-issue sessions run at once (1 to 5). A grind posts to the repo's Slack review channel. Each row saves as soon as you change it.</p>
            ${repos.length === 0 && html`<p class="muted">No repos registered yet.</p>`}
            ${repos.length > REPO_PREVIEW && html`<input type="search" class="field" aria-label="Filter repos" placeholder=${`Filter ${repos.length} repos`} value=${repoQ} onInput=${(e) => this.setState({ repoQ: e.target.value })} />`}
            ${shownRepos.map((r) => repoSection(r.slug, repoRow(cfg, r.slug), rowErr[r.slug], this.saveRepo))}
            ${!repoQ.trim() && !allRepos && repos.length > REPO_PREVIEW && html`<button type="button" onClick=${() => this.setState({ allRepos: true })}>Show all ${repos.length}</button>`}
            ${repoQ.trim() && shownRepos.length === 0 && html`<p class="muted">No repo matches.</p>`}
          </section>`,
          html`<section class="panel" aria-labelledby="repos-h">
            <h2 id="repos-h">Repos</h2>
            <p class="note">aiw works inside a local clone of each repo. Scan your project folders to register every clone that has a GitHub origin, so the boards and New run can find them.</p>
            <label for="scan-roots">Folders to scan, one per line</label>
            <textarea id="scan-roots" class="field mono" rows="3" spellcheck="false" value=${roots} onInput=${(e) => this.setState({ roots: e.target.value })}></textarea>
            <div class="launch-actions">
              <button type="button" disabled=${scanning} onClick=${this.scan}>${scanning ? 'Scanning…' : 'Find my repos'}</button>
              <button type="button" disabled=${checking || !repos.length} onClick=${this.checkRepos}>${checking ? 'Checking…' : 'Check remotes'}</button>
              ${scanMsg && html`<span class="muted" role="status">${scanMsg}</span>`}
            </div>
            ${repos.length > 0 && html`<ul class="repo-list" aria-label="Known repos">
              ${listed.map((r) => html`<li key=${r.slug}><span>${r.slug}</span><span class="mono muted" title=${r.path}>${r.path}</span>
                ${problems && problems[r.slug] && html`<span class="error">${problems[r.slug]}</span>`}
                <button type="button" class="btn-sm btn--danger" aria-label=${`Remove ${r.slug}`} onClick=${() => this.removeRepo(r.slug)}>Remove</button></li>`)}
            </ul>`}
            ${repos.length === 0 && html`<p class="muted">No repos registered yet.</p>`}
          </section>`)}
          ${sec('vault',
          html`<form class="panel" aria-labelledby="vault-h" onSubmit=${this.saveVault} noValidate>
            <h2 id="vault-h">Notes vault</h2>
            <p class="note">The Obsidian vault <code>/dump</code> and <code>/create-prd</code> write to. New run lists its project folders, so you can start those runs without a repo.</p>
            <label for="vault-dir">Vault folder</label>
            <input id="vault-dir" type="text" class="field mono" spellcheck="false" placeholder="~/Documents/notes" value=${vault}
              aria-invalid=${vaultMsg ? 'true' : undefined} aria-describedby=${vaultMsg ? 'vault-err' : undefined}
              onInput=${(e) => this.setState({ vault: e.target.value })} />
            ${vaultMsg && html`<p id="vault-err" role="alert" class="error">${vaultMsg}</p>`}
            <div class="launch-actions"><button type="submit" disabled=${saving}>Save vault folder</button></div>
          </form>`)}
          ${sec('notifications', html`<${NotifyPanel} />`)}
          ${sec('review', html`<${ReviewPanel} />`)}
        </div>
        </div>
      </section>`;
  }
}
