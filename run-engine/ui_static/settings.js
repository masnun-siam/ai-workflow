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
  state = { commands: null, def: '', tests: {}, err: '', saving: false };

  async componentDidMount() {
    try {
      const s = await api('GET', '/api/settings');
      this.setState({ commands: s.commands, def: s.default || '' });
    } catch (e) {
      this.setState({ commands: [], err: e.message });
    }
  }

  edit = (i, k) => (e) => this.setState(({ commands }) => ({ commands: commands.map((c, j) => (j === i ? { ...c, [k]: e.target.value } : c)) }));

  add = () => this.setState(({ commands }) => ({ commands: [...commands, { label: '', cmd: '' }] }));

  remove = (i) => this.setState(({ commands, def }) => ({
    commands: commands.filter((_, j) => j !== i),
    def: def === commands[i].label ? '' : def,
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

  save = async (e) => {
    e.preventDefault();
    const { commands, def } = this.state;
    this.setState({ saving: true, err: '' });
    try {
      const s = await api('PUT', '/api/settings', { commands, default: def || null });
      this.setState({ commands: s.commands, def: s.default || '' });
      toast('Settings saved');
    } catch (er) {
      this.setState({ err: er.message });
    }
    this.setState({ saving: false });
  };

  render(_, { commands, def, tests, err, saving }) {
    if (!commands) return html`<h1>Settings</h1><p role="status">Loading…</p>`;
    return html`
      <section class="settings">
        <h1>Settings</h1>
        <div class="settings-cols">
          <nav class="settings-menu" aria-label="Settings"><a href="#/settings" aria-current="page">Claude commands</a></nav>
          <form class="panel" onSubmit=${this.save} noValidate>
            <h2>Claude commands</h2>
            <p class="note">The command a run is launched with. Use <code>cc masum</code> to run under another account. The default is <code>claude</code> when nothing is set.</p>
            ${commands.map((c, i) => html`
              <div class="cmd-row" key=${i}>
                <input aria-label="Label" placeholder="Label (Masum)" value=${c.label} onInput=${this.edit(i, 'label')} />
                <input aria-label="Command" class="mono" placeholder="cc masum" value=${c.cmd} onInput=${this.edit(i, 'cmd')} />
                <label class="radio"><input type="radio" name="default" checked=${!!c.label && def === c.label} disabled=${!c.label} onChange=${() => this.setState({ def: c.label })} /> default</label>
                <button type="button" onClick=${() => this.test(i)}>Test</button>
                <button type="button" class="btn--danger" aria-label=${`Remove ${c.label || 'command'}`} onClick=${() => this.remove(i)}>Remove</button>
                ${tests[i] && html`<span class=${tests[i].ok === false ? 'error' : 'muted'} role="status">${tests[i].message || tests[i].msg}</span>`}
              </div>`)}
            ${commands.length === 0 && html`<p class="muted">No commands saved: runs use <code>claude</code>.</p>`}
            ${err && html`<p role="alert" class="error">${err}</p>`}
            <div class="launch-actions">
              <button type="button" onClick=${this.add}>Add command</button>
              <button type="submit" disabled=${saving}>${saving ? 'Saving…' : 'Save'}</button>
            </div>
          </form>
        </div>
      </section>`;
  }
}
