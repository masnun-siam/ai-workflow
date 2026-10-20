import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { BoardShell, sendJson } from './boardshell.js';
import { toast } from './toast.js';
import { PanelControl } from './panel.js';
import { openPrd } from './prd.js';

const html = htm.bind(h);

export const COLUMNS = [
  ['draft', 'PRD draft'],
  ['in_review', 'In review'],
  ['approved', 'Approved'],
  ['tasks_filed', 'Tasks filed'],
  ['refined', 'Refined'],
];

// The backend decides the column (ui_planning.build): draft | in_review | approved | tasks_filed | refined.
export const columnOf = (p) => p.column;

export function groupPrds(prds) {
  const by = Object.fromEntries(COLUMNS.map(([k]) => [k, []]));
  for (const p of prds || []) by[columnOf(p)].push(p);
  return by;
}

// The next action for a card: [label, request body] for POST /api/start or /api/autopilot, or null.
export function actionFor(p, repo) {
  switch (columnOf(p)) {
    case 'approved': return { label: 'Create tasks', url: '/api/start', body: { repo, skill: 'create-tasks', arg: p.path, via: 'headless' } };
    case 'tasks_filed': {
      // No epic (issues only labelled prd-<slug>): refine-issues also takes the issue numbers.
      const arg = p.epic ? String(p.epic) : (p.unrefined || []).join(' ');
      return arg ? { label: 'Refine', url: '/api/start', body: { repo, skill: 'refine-issues', arg, via: 'headless' } } : null;
    }
    case 'refined': return p.epic ? { label: 'Autopilot', url: '/api/autopilot', body: { repo, epic: p.epic, on: true } } : null;
    default: return null;
  }
}

export function cardDetail(p) {
  const col = columnOf(p);
  const d = [];
  if (col === 'in_review' && p.pr) d.push(`PR #${p.pr.n}`);
  if (p.epic && col !== 'draft' && col !== 'in_review') d.push(`Epic #${p.epic}`);
  if (col === 'tasks_filed' || col === 'refined') d.push(`${p.issues} issue${p.issues === 1 ? '' : 's'}`, `${p.refined}/${p.issues} refined`);
  return d;
}

// Card for a PRD. Plain function, so tests can walk the tree.
export function prdCard(p, repo, { busy, err, session, onAct, offers, onChange }) {
  const act = actionFor(p, repo);
  return html`<article class="bcard" key=${p.path || p.slug}>
    <div class="bcard-title"><a href=${`#/planning`} onClick=${(e) => { e.preventDefault(); openPrd(repo, p.path, p.title || p.slug); }}>${p.title || p.slug}</a></div>
    <div class="bcard-meta"><span>${p.status}</span>${cardDetail(p).map((t) => html`<span>${t}</span>`)}</div>
    ${columnOf(p) === 'draft' && html`<div class="bcard-slot" data-slot="panel"><${PanelControl} repo=${repo} artifact=${p.abs_path} panel=${p.panel} offers=${offers} onChange=${onChange} /></div>`}
    ${act && html`<div class="bcard-actions"><button type="button" disabled=${busy} onClick=${() => onAct(p, act)}>${busy ? 'Starting…' : act.label}</button></div>`}
    ${session && html`<a href=${`#/session/${encodeURIComponent(session)}`}>Open session</a>`}
    ${err && html`<p role="alert" class="error">${err}</p>`}
  </article>`;
}

class PlanningBoard extends Component {
  state = { busy: {}, err: {}, sessions: {}, offers: null };

  componentDidMount() {
    fetch('/api/peer-review', { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .then((o) => o && !this.gone && this.setState({ offers: o }))
      .catch(() => {}); // no picker without offers
  }

  componentWillUnmount() {
    this.gone = true;
  }

  act = async (p, act) => {
    const k = p.path || p.slug;
    this.setState(({ busy, err }) => ({ busy: { ...busy, [k]: true }, err: { ...err, [k]: '' } }));
    const r = await sendJson('POST', act.url, act.body);
    this.setState(({ busy, err, sessions }) => ({
      busy: { ...busy, [k]: false },
      err: { ...err, [k]: r.ok ? '' : r.error },
      sessions: r.ok && r.data.session ? { ...sessions, [k]: r.data.session } : sessions,
    }));
    if (r.ok) {
      toast(`${act.label} started`);
      this.props.ctx.reload();
    }
  };

  render({ data, ctx }, { busy, err, sessions, offers }) {
    const prds = data.prds || [];
    if (!prds.length) return html`<p class="board-empty hint" role="status">No PRDs in this repo yet. Run <code>/create-prd</code> to write one.</p>`;
    const by = groupPrds(prds);
    return html`<div class="cols">
      ${COLUMNS.map(([k, label]) => html`<section class="bcol" aria-label=${label} key=${k}>
        <h2>${label}<span>${by[k].length}</span></h2>
        ${by[k].length ? by[k].map((p) => prdCard(p, ctx.repo, { busy: !!busy[p.path || p.slug], err: err[p.path || p.slug], session: sessions[p.path || p.slug], onAct: this.act, offers, onChange: ctx.reload })) : html`<p class="empty">None</p>`}
      </section>`)}
    </div>`;
  }
}

export function Planning() {
  return html`<${BoardShell} title="Planning" path="/api/planning" render=${(data, ctx) => html`<${PlanningBoard} data=${data} ctx=${ctx} />`} />`;
}
export { PlanningBoard };
