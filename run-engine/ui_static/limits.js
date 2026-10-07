import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { clockText, untilText } from './fmt.js';
import { toast } from './toast.js';

const html = htm.bind(h);

async function post(id, action, body) {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(id)}/${action}`, {
      method: 'POST',
      ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
    });
    if (res.ok) return { ok: true };
    return { ok: false, error: (await res.json().catch(() => ({}))).error || `HTTP ${res.status}` };
  } catch (e) {
    return { ok: false, error: String(e?.message || e) };
  }
}

// Shown on a limited run: when it resumes, plus Resume now / Cancel auto-resume / Resume on another account.
export class LimitBanner extends Component {
  state = { now: Date.now(), cmds: [], pick: '', busy: false, err: '' };

  async componentDidMount() {
    this.tick = setInterval(() => this.setState({ now: Date.now() }), 15000);
    try {
      const res = await fetch('/api/settings', { headers: { Accept: 'application/json' } });
      if (res.ok) this.setState({ cmds: (await res.json()).commands || [] });
    } catch {
      // no switch-account choices without settings
    }
  }

  componentWillUnmount() {
    clearInterval(this.tick);
  }

  go = async (action, body, done) => {
    this.setState({ busy: true, err: '' });
    const r = await post(this.props.s.id, action, body);
    this.setState({ busy: false, err: r.ok ? '' : r.error });
    toast(r.ok ? done : `${action} failed: ${r.error}`, r.ok ? 'ok' : 'error');
  };

  render({ s }, { now, cmds, pick, busy, err }) {
    const at = s.limit_resets_at;
    const others = cmds.filter((c) => c.cmd !== (s.claude_cmd || 'claude'));
    const label = (cmds.find((c) => c.cmd === s.claude_cmd) || {}).label || s.claude_cmd || 'claude';
    return html`
      <div class="limit-banner" role="status">
        <div>
          <strong>Limited</strong> on <span class="mono">${label}</span>${at
            ? html` · resets ${clockText(at)} (${untilText(at, now)}) · ${s.auto_resume ? 'resumes automatically' : 'auto-resume cancelled'}`
            : ' · reset time unknown, resume manually'}
          ${s.note && html`<span class="muted"> · ${s.note}</span>`}
        </div>
        <div class="actions">
          <button type="button" disabled=${busy} onClick=${() => this.go('resume', null, 'Resumed')}>Resume now</button>
          ${s.auto_resume && html`<button type="button" disabled=${busy} onClick=${() => this.go('cancel-auto', null, 'Auto-resume cancelled')}>Cancel auto-resume</button>`}
          ${others.length > 0 && html`
            <select aria-label="Account to resume on" value=${pick} onChange=${(e) => this.setState({ pick: e.target.value })}>
              <option value="">Another account…</option>
              ${others.map((c) => html`<option value=${c.label}>${c.label}</option>`)}
            </select>
            <button type="button" disabled=${busy || !pick} onClick=${() => this.go('resume', { claude_cmd: pick }, `Resumed on ${pick}`)}>Resume there</button>`}
        </div>
        ${err && html`<p role="alert" class="error">${err}</p>`}
      </div>`;
  }
}
