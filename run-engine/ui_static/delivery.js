import { h } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { BoardShell } from './boardshell.js';
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

export function lane(l, ctx = {}) {
  const by = laneGroups(l.cards);
  const atCap = l.running >= l.cap;
  return html`<section class="lane" aria-label=${l.epic ? `Epic #${l.epic}` : 'No epic'} key=${l.epic || 'none'}>
    <div class="lane-head">
      <h2>${l.epic ? `#${l.epic} ${l.title || ''}` : 'No epic'}</h2>
      <span class=${atCap ? 'lane-running at-cap' : 'lane-running'}>${runningText(l.running, l.cap)}</span>
      ${l.autopilot && html`<span class="chip chip-running">autopilot on</span>`}
      <span data-slot="lane-actions"><${LaneAutopilot} lane=${l} repo=${ctx.repo} onChange=${ctx.reload} /></span>
    </div>
    <div class="cols">
      ${COLUMNS.map(([k, label]) => html`<section class="bcol" aria-label=${label} key=${k}>
        <h2>${label}<span>${by[k].length}</span></h2>
        ${by[k].length ? by[k].map((c) => deliveryCard(c, ctx)) : html`<p class="empty">None</p>`}
      </section>`)}
    </div>
  </section>`;
}

export function board(data, ctx = {}) {
  const lanes = data.lanes || [];
  if (!lanes.length) return html`<p class="board-empty" role="status">Nothing to deliver yet. Refined issues appear here.</p>`;
  return html`${lanes.map((l) => lane(l, { ...ctx, autoGrind: data.auto_grind }))}`;
}

export function Delivery() {
  return html`<${BoardShell} title="Delivery" path="/api/delivery" render=${board} />`;
}
