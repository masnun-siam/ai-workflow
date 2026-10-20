import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { BoardShell, colTabs } from './boardshell.js';
import { ghChips } from './ghstatus.js';
import { CardActions, LaneAutopilot } from './delivery_actions.js';
import { IssueLink } from './issue.js';
import { PrLink } from './pr.js';

const html = htm.bind(h);

export const COLUMNS = [
  ['ready', 'Ready'],
  ['in_progress', 'In progress'],
  ['draft_pr', 'Draft PR'],
  ['in_review', 'In review'],
  ['grinding', 'Grinding'],
  ['merged', 'Merged'],
];

export function laneGroups(cards) {
  const by = Object.fromEntries(COLUMNS.map(([k]) => [k, []]));
  for (const c of cards || []) (by[c.column] || by.ready).push(c);
  return by;
}

export const runningText = (running, cap) => `${running}/${cap} running`;

// CI chip from ghstatus.js: its first chip is the CI one when the PR has a ci state.
export const ciChip = (pr) => (pr && pr.ci ? ghChips({ pr: { state: 'OPEN', ci: pr.ci } }).slice(0, 1) : []);

// Card. Plain function so tests can walk the tree. `ctx` = { repo, autoGrind, reload }.
export function deliveryCard(c, ctx = {}) {
  const blocked = (c.blocked_by || []).length > 0;
  const [owner, repo] = String(ctx.repo || '').split('/');
  return html`<article class=${blocked ? 'bcard is-blocked' : 'bcard'} key=${c.n}>
    <div class="bcard-title">${owner && repo ? html`<${IssueLink} owner=${owner} repo=${repo} issue=${c.n}>#${c.n} ${c.title}<//>` : `#${c.n} ${c.title}`}</div>
    <div class="bcard-meta">
      ${c.priority && html`<span class="chip gh-label">${c.priority}</span>`}
      ${blocked && html`<span class="lock" title="Cannot start until these close"><span aria-hidden="true">🔒</span> Blocked by ${c.blocked_by.map((n) => `#${n}`).join(', ')}</span>`}
      ${c.pr && html`<${PrLink} url=${c.pr.url}>PR #${c.pr.n}${c.pr.draft ? ' (draft)' : ''}<//>`}
      ${ciChip(c.pr).map((x) => html`<span class=${'chip gh-' + x.tone}>${x.text}</span>`)}
      ${c.session && html`<a class="chip chip-running" href=${`#/session/${encodeURIComponent(c.session.id)}`}>session</a>`}
      ${c.grind_round ? html`<span class="chip chip-grind-running">grind round ${c.grind_round}</span>` : null}
      ${c.needs_cleanup && html`<span class="chip gh-warn">needs cleanup</span>`}
    </div>
    <div class="bcard-slot" data-slot="actions"><${CardActions} card=${c} repo=${ctx.repo} autoGrind=${ctx.autoGrind} onChange=${ctx.reload} /></div>
  </article>`;
}

// Open work in a lane: everything not yet merged. A lane without any starts collapsed.
export const openCount = (l) => (l.cards || []).filter((c) => c.column !== 'merged').length;

export function lane(l, ctx = {}) {
  const by = laneGroups(l.cards);
  const atCap = l.running >= l.cap;
  const key = `lane-${l.epic || 'none'}`;
  const open = openCount(l);
  return html`<details class="lane" aria-label=${l.epic ? `Epic #${l.epic}` : 'No epic'} key=${l.epic || 'none'} open=${open > 0 || !!ctx.only}>
    <summary class="lane-head">
      <h2>${l.epic ? `#${l.epic} ${l.title || ''}` : 'No epic'}</h2>
      <span class=${atCap ? 'lane-running at-cap' : 'lane-running'}>${runningText(l.running, l.cap)}</span>
      ${l.autopilot && html`<span class="chip chip-running">autopilot on</span>`}
      ${!open && html`<span class="muted lane-empty">nothing open</span>`}
      <span data-slot="lane-actions"><${LaneAutopilot} lane=${l} repo=${ctx.repo} onChange=${ctx.reload} /></span>
    </summary>
    ${colTabs(key, COLUMNS.map(([k, label]) => [k, label, by[k].length]))}
    <div class="cols">
      ${COLUMNS.map(([k, label]) => html`<section class="bcol" id=${`${key}-${k}`} aria-label=${label} key=${k}>
        <h2>${label}<span>${by[k].length}</span></h2>
        ${by[k].length ? by[k].map((c) => deliveryCard(c, ctx)) : html`<p class="empty">None</p>`}
      </section>`)}
    </div>
  </details>`;
}

export function board(data, ctx = {}) {
  const lanes = data.lanes || [];
  if (!lanes.length) return html`<p class="board-empty" role="status">Nothing to deliver yet. Refined issues appear here.</p>`;
  const only = ctx.epic ? lanes.filter((l) => String(l.epic || 'none') === ctx.epic) : lanes;
  return html`${only.map((l) => lane(l, { ...ctx, autoGrind: data.auto_grind, only: !!ctx.epic }))}`;
}

export const epicLabel = (l) => (l.epic ? `#${l.epic} ${l.title || ''}`.trim() : 'No epic');

// The board plus an epic filter (kept per page visit; "All epics" by default).
class DeliveryBoard extends Component {
  state = { epic: '' };

  render({ data, ctx }, { epic }) {
    const lanes = data.lanes || [];
    const known = lanes.some((l) => String(l.epic || 'none') === epic) ? epic : '';
    return html`${lanes.length > 1 && html`<label class="epic-filter">Epic
        <select onChange=${(e) => this.setState({ epic: e.target.value })}>
          <option value="" selected=${!known}>All epics (${lanes.length})</option>
          ${lanes.map((l) => html`<option value=${String(l.epic || 'none')} selected=${known === String(l.epic || 'none')}>${epicLabel(l)} · ${openCount(l)} open</option>`)}
        </select></label>`}
      ${board(data, { ...ctx, epic: known })}`;
  }
}

export function Delivery() {
  return html`<${BoardShell} title="Delivery" path="/api/delivery" render=${(data, ctx) => html`<${DeliveryBoard} data=${data} ctx=${ctx} />`} />`;
}
export { DeliveryBoard };
