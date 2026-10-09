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

export class Settings extends Component {
  saved = { commands: [], default: null };
  state = { commands: null, def: '', autoGrind: false, tests: {}, err: '', saving: false, repos: [], roots: '', scanning: false, scanMsg: '' };

  async componentDidMount() {
    try {
      const s = await api('GET', '/api/settings');
      this.saved = { commands: s.commands, default: s.default };
      this.setState({ commands: s.commands, def: s.default || '', autoGrind: !!s.auto_grind });
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

  // The grinding default saves on its own, with the last *saved* commands, so half-edited command rows stay put.
  setAutoGrind = async (e) => {
    const on = e.target.checked;
    this.setState({ autoGrind: on, err: '', saving: true });
    try {
      const s = await api('PUT', '/api/settings', { ...this.saved, auto_grind: on });
      this.saved = { commands: s.commands, default: s.default };
      toast(on ? 'Grinding will start automatically' : 'Grinding will wait for you to start it');
    } catch (er) {
      this.setState({ autoGrind: !on, err: er.message });
    }
    this.setState({ saving: false });
  };

  save = async (e) => {
    e.preventDefault();
    const { commands, def, autoGrind } = this.state;
    this.setState({ saving: true, err: '' });
    try {
      const s = await api('PUT', '/api/settings', { commands, default: def || null, auto_grind: autoGrind });
      this.saved = { commands: s.commands, default: s.default };
      this.setState({ commands: s.commands, def: s.default || '', autoGrind: !!s.auto_grind });
      toast('Settings saved');
    } catch (er) {
      this.setState({ err: er.message });
    }
    this.setState({ saving: false });
  };

  render(_, { commands, def, autoGrind, tests, err, saving, repos, roots, scanning, scanMsg }) {
    if (!commands) return html`<h1>Settings</h1><p role="status">Loading…</p>`;
    return html`
      <section class="settings">
        <h1>Settings</h1>
        <div class="settings-main">
          <form class="panel" onSubmit=${this.save} noValidate>
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
          </form>
          <section class="panel" aria-labelledby="grind-h">
            <h2 id="grind-h">Review grinding</h2>
            <label class="check"><input type="checkbox" checked=${autoGrind} disabled=${saving} onChange=${this.setAutoGrind} /> Start grinding when a run finishes</label>
            <p class="note">The default for new runs and pipelines; each can override it. A grind posts to the repo's Slack review channel. Saved as soon as you change it.</p>
          </section>
          <section class="panel" aria-labelledby="repos-h">
            <h2 id="repos-h">Repos</h2>
            <p class="note">aiw works inside a local clone of each repo. Scan your project folders to register every clone that has a GitHub origin, so Dispatch and New run can find them.</p>
            <label for="scan-roots">Folders to scan, one per line</label>
            <textarea id="scan-roots" class="field mono" rows="3" spellcheck="false" value=${roots} onInput=${(e) => this.setState({ roots: e.target.value })}></textarea>
            <div class="launch-actions">
              <button type="button" disabled=${scanning} onClick=${this.scan}>${scanning ? 'Scanning…' : 'Find my repos'}</button>
              ${scanMsg && html`<span class="muted" role="status">${scanMsg}</span>`}
            </div>
            ${repos.length > 0 && html`<ul class="repo-list" aria-label="Known repos">
              ${repos.map((r) => html`<li><span>${r.slug}</span><span class="mono muted" title=${r.path}>${r.path}</span></li>`)}
            </ul>`}
            ${repos.length === 0 && html`<p class="muted">No repos registered yet.</p>`}
          </section>
        </div>
      </section>`;
  }
}
