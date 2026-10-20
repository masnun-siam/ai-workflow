import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { sendJson } from './boardshell.js';
import { toast } from './toast.js';

const html = htm.bind(h);

export const isBlocked = (c) => (c.blocked_by || []).length > 0;
export const startBody = (repo, c, via) => ({ repo, skill: 'implement-issue', arg: String(c.n), via });
export const grindBody = (repo, c) => ({ repo, skill: 'pr-grind', arg: c.pr.url, via: 'headless' });
// Grind is offered on In review cards only while the repo's auto-grind is off (FR-10).
export const canGrind = (c, autoGrind) => c.column === 'in_review' && !autoGrind && !!(c.pr && c.pr.url);

// Start / Start in herdr / Grind / Clean for one card. A refused request (409) toasts and starts nothing.
export class CardActions extends Component {
  state = { busy: false, clean: false };

  post = async (url, body, done) => {
    this.setState({ busy: true });
    const r = await sendJson('POST', url, body);
    this.setState({ busy: false, clean: r.ok ? false : this.state.clean });
    if (r.ok) {
      toast(done);
      if (this.props.onChange) this.props.onChange();
    } else toast(r.error, 'error');
  };

  start = (via) => this.post('/api/start', startBody(this.props.repo, this.props.card, via), 'Started');
  grind = () => this.post('/api/start', grindBody(this.props.repo, this.props.card), 'Grind started');
  clean = () => this.post('/api/cleanup', { repo: this.props.repo, issue: this.props.card.n, confirm: true }, 'Cleaned up');

  render({ card, autoGrind }, { busy, clean }) {
    const btn = (label, onClick, disabled, title) => html`<button type="button" disabled=${busy || disabled} title=${title} onClick=${onClick}>${label}</button>`;
    const blocked = isBlocked(card);
    const why = blocked ? 'Blocked: its blockers must close first' : undefined;
    const nc = card.needs_cleanup;
    return html`<div class="bcard-actions">
      ${card.column === 'ready' && btn('Start', () => this.start('headless'), blocked, why)}
      ${card.column === 'ready' && btn('Start in herdr', () => this.start('herdr'), blocked, why)}
      ${canGrind(card, autoGrind) && btn('Grind', this.grind)}
      ${card.column === 'merged' && nc && btn('Clean', () => this.setState({ clean: true }))}
      ${clean && nc && html`<div class="clean-dialog" role="dialog" aria-label=${`Clean up #${card.n}`}>
        <p>Cleaning up #${card.n} removes its worktree and branch. This will be lost:</p>
        <p>Uncommitted files</p>
        ${(nc.uncommitted || []).length ? html`<ul>${nc.uncommitted.map((f) => html`<li class="mono">${f}</li>`)}</ul>` : html`<p class="muted">None</p>`}
        <p>Unpushed commits</p>
        ${(nc.unpushed || []).length ? html`<ul>${nc.unpushed.map((s) => html`<li class="mono">${s}</li>`)}</ul>` : html`<p class="muted">None</p>`}
        ${btn('Clean up', this.clean)}
        <button type="button" disabled=${busy} onClick=${() => this.setState({ clean: false })}>Cancel</button>
      </div>`}
    </div>`;
  }
}

// The lane's autopilot switch (POST /api/autopilot). The server's answer decides the next board; a refusal toasts.
export class LaneAutopilot extends Component {
  state = { busy: false };

  toggle = async () => {
    const { repo, lane } = this.props;
    this.setState({ busy: true });
    const r = await sendJson('POST', '/api/autopilot', { repo, epic: lane.epic, on: !lane.autopilot });
    this.setState({ busy: false });
    if (r.ok) {
      if (this.props.onChange) this.props.onChange();
    } else toast(r.error, 'error');
  };

  render({ lane }, { busy }) {
    if (!lane.epic) return null;
    return html`<label class="check"><input type="checkbox" role="switch" checked=${lane.autopilot} disabled=${busy} onChange=${this.toggle} /> Autopilot</label>`;
  }
}
