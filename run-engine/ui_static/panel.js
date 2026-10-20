import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { sendJson } from './boardshell.js';
import { lensPicker, lensName, pickedLenses } from './launcher.js';
import { toast } from './toast.js';

const html = htm.bind(h);

// POST /api/review validates against the "custom" kind (ui_panel.start), so that is the offered set.
export const PANEL_KIND = 'custom';
export const offerFor = (offers) => (offers && offers.kinds && offers.kinds[PANEL_KIND]) || [];

export const progressText = (p) => `${p.approved}/${p.total}, round ${p.round}`;
export const isCapReached = (p) => !!p && p.state === 'cap reached';
export const failedLenses = (p) => Object.entries((p && p.lenses) || {}).filter(([, v]) => v === 'failed').map(([l]) => l);

// panel: the planning card's `peer_review.panel_status` + id + root_session, or an optimistic {approved:0,total,round:1}.
export function panelView(panel, { onLens, busy }) {
  const failed = failedLenses(panel);
  return html`<div class="panel-progress">
    <p class="panel-count" role="status">Review ${progressText(panel)}${panel.state && panel.state !== 'running' ? ` · ${panel.state}` : ''}${panel.reason ? ` (${panel.reason})` : ''}</p>
    ${isCapReached(panel) && panel.root_session && html`<p>Cap reached. <a href=${`#/session/${encodeURIComponent(panel.root_session)}`}>Open the root session</a></p>`}
    ${isCapReached(panel) && !panel.root_session && html`<p>Cap reached.</p>`}
    ${failed.map((l) => html`<div class="lens-failed" key=${l}>
      <span>${lensName(l)} failed</span>
      <button type="button" disabled=${busy} onClick=${() => onLens(l, 'rerun')}>Re-run</button>
      <button type="button" disabled=${busy} onClick=${() => onLens(l, 'drop')}>Drop</button>
    </div>`)}
  </div>`;
}

// <PanelControl repo artifact panel offers onChange>: lens picker + Start on a draft PRD, progress once a panel exists.
export class PanelControl extends Component {
  state = { on: false, picked: null, busy: false, err: '', started: null };

  start = async () => {
    const { repo, artifact, offers } = this.props;
    const lenses = pickedLenses(true, this.state.picked, offers);
    if (!lenses.length) return this.setState({ err: 'Tick at least one reviewer' });
    this.setState({ busy: true, err: '' });
    const r = await sendJson('POST', '/api/review', { repo, artifact, lenses });
    this.setState({ busy: false, err: r.ok ? '' : r.error, started: r.ok ? { id: r.data.panel, total: lenses.length } : this.state.started });
    if (r.ok) {
      toast('Review started');
      if (this.props.onChange) this.props.onChange();
    }
  };

  lens = async (lens, action) => {
    const { panel } = this.props;
    const id = (panel && panel.id) || (this.state.started && this.state.started.id);
    this.setState({ busy: true, err: '' });
    const r = await sendJson('POST', `/api/review/${encodeURIComponent(id)}/lens`, { lens, action });
    this.setState({ busy: false, err: r.ok ? '' : r.error });
    if (r.ok && this.props.onChange) this.props.onChange();
  };

  render({ panel, offers, repo }, { on, picked, busy, err, started }) {
    const shown = panel || (started && { approved: 0, total: started.total, round: 1, state: 'running', lenses: {}, id: started.id });
    const offer = offerFor(offers);
    const id = 'panel-' + String(repo || '').replace(/\W/g, '') + '-' + (this.props.artifact || '').replace(/\W/g, '');
    return html`<div class="panel-control">
      ${shown ? panelView(shown, { onLens: this.lens, busy }) : html`
        ${lensPicker({ id, offer, on, picked: picked || (offers && offers.default), rounds: offers && offers.max_rounds, disabled: busy,
          onToggle: (v) => this.setState({ on: v }), onPick: (l) => this.setState({ picked: l }) })}
        ${on && html`<button type="button" disabled=${busy} onClick=${this.start}>${busy ? 'Starting…' : 'Start review'}</button>`}`}
      ${err && html`<p role="alert" class="error">${err}</p>`}
    </div>`;
  }
}
