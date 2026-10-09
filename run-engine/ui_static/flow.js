import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { poll } from './app.js';
import { buildBody, loadLastRepo, repoCombo, repoOptions } from './launcher.js';
import { issueNumbers } from './dispatch.js';
import { Answer } from './answer.js';
import { FlowSwitcher, IssueRows, NotePane, mergeRows } from './flowside.js';

const html = htm.bind(h);

// Guided Flow (#190): Dump → PRD → Issues → Dispatch. Each step runs its command as a headless
// session; its final `→ next:` line pre-fills the next step. Each flow is a server record
// (ui_flows.py) at #/flow/<id>; the bare #/flow opens the most recently active one.
const STEPS = [
  { key: 'dump', label: 'Dump', command: 'dump', action: 'File the idea', input: 'What do you want built or fixed?',
    placeholder: 'e.g. Admins can export the bookings table as CSV, filtered by date range',
    produces: 'Files the idea into a feature folder in your notes.' },
  { key: 'prd', label: 'PRD', command: 'prd', action: 'Write the PRD', input: 'Feature folder (05-Work/<Project>/<Feature>)',
    produces: 'Writes a reviewed PRD for the feature.' },
  { key: 'issues', label: 'Issues', command: 'gh-issue', action: 'Create the issues', input: 'PRD path, or the Bugs.md / Tasks.md note',
    produces: 'Creates GitHub issues from the PRD.' },
  { key: 'dispatch', label: 'Dispatch', input: 'Issue numbers', produces: 'Starts a run for each issue.' },
];
const STATE_TEXT = { done: 'Done', skipped: 'Skipped', active: 'Current step', locked: 'Not started' };
const TERMINAL = ['done', 'failed', 'stopped'];

// The last `→ next: <command> <arg>` line of a session's final result, or null. Tolerates the
// line being indented or wrapped in a code span or bold, since models often format it.
export function parseNext(text) {
  const all = [...String(text || '').matchAll(/^[ \t]*[`*]*→ next: (\S+)[ \t]*(.*?)[`*]*[ \t]*$/gm)];
  const m = all.at(-1);
  return m ? { command: m[1], arg: m[2].trim() } : null;
}

// Which fields a step's `→ next:` line may fill; a line naming any other command does not unlock.
const NEXT = { dump: { prd: 'folder', 'gh-issue': 'prd' }, prd: { 'gh-issue': 'prd' }, issues: { 'herdr-dispatch': 'issues' } };

// Turn a step's final `result` event into a state patch, or {error} saying why the next step stays locked.
export function handoff(step, result) {
  if (!result) return { error: 'The session ended without a final result.' };
  if (result.is_error) return { error: 'The session failed. Continue in terminal.' };
  const next = parseNext(result.text);
  if (!next) return { error: step === 'dump' ? 'No → next: line found: dump ends the flow for a standalone task, meeting notes or unclassifiable.' : 'The result has no → next: line.' };
  const field = (NEXT[step] || {})[next.command.replace(/^\//, '').split(':').pop()];
  if (!field) return { error: `Unexpected next command: ${next.command}` };
  if (field === 'issues') {
    const issues = issueNumbers(next.arg);
    return issues.length ? { issues } : { error: 'The → next: line lists no issue numbers.' };
  }
  return next.arg ? { [field]: next.arg } : { error: 'The → next: line has no argument.' };
}

// The first step whose input is known but whose output isn't.
export function stepFromState({ folder, prd, issues } = {}) {
  if (issues && issues.length) return 'dispatch';
  if (prd) return 'issues';
  if (folder) return 'prd';
  return 'dump';
}

export function flowHash({ repo, folder, prd, issues, sid } = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries({ repo, folder, prd, sid })) if (v) q.set(k, v);
  if (issues && issues.length) q.set('issues', issues.join(','));
  const s = q.toString().replaceAll('%2C', ',');
  return s ? `#/flow?${s}` : '#/flow';
}

export const dispatchHref = (issues) => `#/dispatch?issues=${issues.join(',')}`;

export const flowHref = (id) => `#/flow/${encodeURIComponent(id)}`;

// The step a session ran, from its command (`/ai-workflow:gh-issue …` → issues), or null.
export function sessionStep(command) {
  const cmd = (/^\/(?:[\w-]+:)?([\w-]+)/.exec(command || '') || [])[1];
  return (STEPS.find((s) => s.command === cmd) || {}).key || null;
}

// Nav progress for a flow summary from /api/flows: steps passed, or null when nothing has run.
// A typed-but-unrun draft is not progress: a step must have handed off or be running.
export function flowProgress(summary) {
  if (!summary) return null;
  const done = STEPS.findIndex((s) => s.key === summary.step);
  return done > 0 || summary.running ? { done, total: STEPS.length } : null;
}

// "Continue in Flow" on a session page: the session's own flow, or a new flow built from it.
export function flowLink(meta) {
  if (!meta || !sessionStep(meta.command)) return null;
  return meta.flow_id ? flowHref(meta.flow_id) : flowHash({ repo: meta.repo, sid: meta.id });
}

// What the right column shows when no question is waiting: the selected step's output.
// `view` is a step the user clicked on the rail; otherwise the running step, else the last done one.
export function sideView({ view, at, runStep, folder, prd }) {
  const key = view || runStep || (at > 0 ? STEPS[at - 1].key : null);
  if (!key) return null;
  if (key === 'issues' || key === 'dispatch') return { kind: 'issues' };
  if (key === 'dump') {
    if (runStep === 'dump') return { kind: 'filing' };
    return folder ? { kind: 'note', path: `${folder.replace(/\/+$/, '')}/Dump.md` } : prd ? { kind: 'note', path: prd } : null;
  }
  if (runStep === 'prd' && folder) return { kind: 'note', path: `${folder.replace(/\/+$/, '')}/PRD.md`, stale: true };
  return prd ? { kind: 'note', path: prd } : null;
}

const api = async (method, url, body) => {
  const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) });
  const data = await res.json().catch(() => null);
  return { ok: res.ok, status: res.status, data };
};

export class Flow extends Component {
  constructor(props) {
    super(props);
    const p = props.route.params;
    const repo = p.repo || loadLastRepo(globalThis.localStorage) || '';
    this.state = { id: null, loaded: false, missing: false, ...this.repoState(repo), repos: [], canBrowse: false, repoQuery: null,
      repoOpen: false, repoActive: 0, browsing: false, text: '', folder: p.folder || '', prd: p.prd || '', issues: (p.issues || []).join(' '),
      sid: p.sid || '', meta: null, why: null, busy: false, wide: false, view: null, progress: null };
  }

  // The repo is a registered slug or, like New run, an absolute path to a checkout.
  repoState = (repo) => (repo.startsWith('/') ? { repo: '', manual: true, path: repo } : { repo, manual: false, path: '' });

  combo = repoCombo(this, () => this.setState({ why: null }));

  async componentDidMount() {
    // Wide screens give the question and the step's output a column beside the steps.
    this.mq = globalThis.matchMedia?.('(min-width: 1200px)');
    if (this.mq) { this.onMq = () => this.setState({ wide: this.mq.matches }); this.mq.addEventListener('change', this.onMq); this.onMq(); }
    this.loadRepos();
    const p = this.props.route.params;
    try {
      if (p.id && p.id !== 'new') await this.open(p.id);
      else if (p.repo || p.folder || p.prd || p.issues.length || p.sid) await this.persist(true); // an old #/flow?… link becomes a record
      else if (!p.id) {
        const r = await api('GET', '/api/flows');
        const latest = r.ok && r.data && r.data.flows[0];
        if (latest) { history.replaceState(null, '', flowHref(latest.id)); await this.open(latest.id); }
      }
    } catch {
      this.setState({ why: 'Could not reach the aiw server.' });
    }
    if (!this.gone) this.setState({ loaded: true });
    if (this.state.sid) this.watch(this.state.sid);
    this.track();
  }

  componentWillUnmount() {
    this.gone = true;
    if (this.stop) this.stop();
    if (this.stopIssues) this.stopIssues();
    clearTimeout(this.timer);
    if (this.dirty) this.persist(); // flush a pending draft save
    if (this.mq) this.mq.removeEventListener('change', this.onMq);
  }

  async open(id) {
    const r = await api('GET', `/api/flows/${encodeURIComponent(id)}`);
    if (this.gone) return;
    if (!r.ok) { this.setState({ missing: true }); return; }
    const f = r.data;
    this.setState({ id: f.id, ...this.repoState(f.repo || this.fields().repo), text: f.text || '', folder: f.folder || '', prd: f.prd || '',
      issues: (f.issues || []).join(' '), sid: f.sid || '' });
  }

  loadRepos() {
    fetch('/api/repos', { headers: { Accept: 'application/json' } }).then((r) => (r.ok ? r.json() : null)).then((b) => {
      if (this.gone) return;
      const repos = repoOptions(b);
      const { repo, manual, path } = this.state;
      // A checkout path that is a registered repo (a session's repo, say) shows as that repo.
      const known = manual && repos.find((r) => r.path === path);
      this.setState({ repos, canBrowse: !!b && b.can_browse === true, repo: known ? known.value : repo || manual ? repo : (repos[0] || {}).value || '',
        ...(known ? { manual: false, path: '' } : repos.length || manual ? {} : { manual: true, path: repo }) }, () => this.track());
    }).catch(() => {});
  }

  fields = (s = this.state) => ({ repo: (s.manual ? s.path : s.repo).trim(), folder: s.folder, prd: s.prd, issues: issueNumbers(s.issues), sid: s.sid });

  persisted = (s = this.state) => ({ ...this.fields(s), text: s.text });

  componentDidUpdate(_, prev) {
    if (!this.state.loaded || this.gone) return;
    if (JSON.stringify(this.persisted()) !== JSON.stringify(this.persisted(prev))) {
      // Typing saves the draft after a short pause; everything else saves straight away.
      this.dirty = true;
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.persist(), this.state.text !== prev.text ? 600 : 0);
    }
    if (prev.sid !== this.state.sid || prev.view !== this.state.view || prev.meta?.outcome !== this.state.meta?.outcome) this.track();
  }

  // Save to the flow's record, creating it on the first change worth keeping. Returns the id.
  async persist(force = false) {
    this.dirty = false;
    const body = this.persisted();
    if (!this.state.id) {
      if (!force && !body.text.trim() && !body.folder && !body.prd && !body.issues.length && !body.sid) return null;
      if (!this.creating) {
        this.creating = api('POST', '/api/flows', body).then((r) => {
          if (!r.ok || !r.data) return null;
          if (!this.gone) { this.setState({ id: r.data.id }); history.replaceState(null, '', flowHref(r.data.id)); }
          globalThis.dispatchEvent(new Event('aiw:flow'));
          return r.data.id;
        });
      }
      const id = await this.creating;
      this.creating = null;
      if (id && JSON.stringify(this.persisted()) !== JSON.stringify(body)) return this.persist(); // edits made while creating
      return id;
    }
    await api('POST', `/api/flows/${encodeURIComponent(this.state.id)}/update`, body).catch(() => null);
    globalThis.dispatchEvent(new Event('aiw:flow'));
    return this.state.id;
  }

  start = async (step) => {
    const { text, folder, prd } = this.state;
    const { repo } = this.fields();
    const args = { dump: text, prd: folder, issues: prd }[step.key].trim();
    if (!repo || !args) { this.setState({ why: !repo ? 'Pick a repo first.' : 'Fill in the field above first.' }); return; }
    this.setState({ busy: true, why: null, meta: null, view: null });
    clearTimeout(this.timer);
    const flowId = await this.persist(true);
    let r;
    try {
      r = await api('POST', '/api/sessions', { ...buildBody({ repo, command: step.command, args }), ...(flowId ? { flow_id: flowId } : {}) });
    } catch {
      this.setState({ busy: false, why: 'Could not reach the aiw server.' });
      return;
    }
    if (r.status !== 201 || !r.data || !r.data.id) { this.setState({ busy: false, why: (r.data && r.data.error) || `Request failed (HTTP ${r.status})` }); return; }
    this.setState({ busy: false, sid: r.data.id });
    this.watch(r.data.id);
  };

  // Poll the active session at the usual 3 s; once it ends, read its final result and hand off.
  watch(sid) {
    if (this.stop) this.stop();
    this.stop = poll(`/api/sessions/${encodeURIComponent(sid)}`, 3000, (r) => {
      if (!r.ok) { if (r.status === 404) { this.stop(); this.setState({ sid: '', why: 'That session no longer exists.' }); } return; }
      this.setState({ meta: r.data });
      if (TERMINAL.includes(r.data.outcome)) { this.stop(); this.finish(sid, r.data); }
    });
  }

  async finish(sid, meta) {
    // The session's own command names the step it ran, so a session reattached from its page
    // ("Continue in Flow") hands off correctly even when the flow knew nothing before it.
    const step = sessionStep(meta.command) || stepFromState(this.fields());
    let result = null;
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(sid)}/stream?offset=0`, { headers: { Accept: 'application/json' } });
      const body = res.ok ? await res.json() : null;
      result = ((body && body.events) || []).filter((e) => e && e.kind === 'result').at(-1) || null;
    } catch { /* falls through to "no final result" */ }
    if (this.gone) return;
    const out = meta.outcome === 'done' ? handoff(step, result) : { error: `The session ${meta.outcome}. Continue in terminal.` };
    if (out.error) { this.setState({ why: out.error }); return; }
    if (out.issues) out.issues = out.issues.join(' ');
    this.setState({ ...out, sid: '', meta: null, why: null, lastSid: sid });
  }

  // A session is in flight: its step's input stays fixed so the handoff lands on the step that ran.
  running = (s = this.state) => !!s.sid && !(s.meta && TERMINAL.includes(s.meta.outcome));

  // Issue rows: polled while the Issues session runs, read once otherwise.
  track() {
    if (this.stopIssues) { this.stopIssues(); this.stopIssues = null; }
    const v = this.view();
    if (!this.state.id || !v || v.kind !== 'issues') return;
    const url = `/api/flows/${encodeURIComponent(this.state.id)}/issues`;
    if (this.running() && sessionStep(this.state.meta?.command) === 'issues') {
      this.stopIssues = poll(url, 3000, (r) => { if (r.ok) this.gotRows(r.data, false); });
    } else {
      api('GET', url).then((r) => { if (r.ok && !this.gone) this.gotRows(r.data, true); }).catch(() => {});
    }
  }

  // Rows with no usable title (issues created in a shell loop) get it from GitHub, once each.
  gotRows(progress, settled) {
    const merged = settled ? mergeRows(progress, issueNumbers(this.state.issues)) : progress;
    this.titles = this.titles || new Map();
    const [owner, repo] = this.slug().split('/');
    for (const r of merged.rows) {
      if (r.title || !r.number || !owner || !repo) continue;
      if (this.titles.has(r.number)) { r.title = this.titles.get(r.number) || ''; continue; }
      this.titles.set(r.number, '');
      api('GET', `/api/issues/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${r.number}`).then((x) => {
        if (!x.ok || !x.data || !x.data.title || this.gone) return;
        this.titles.set(r.number, x.data.title);
        const p = this.state.progress;
        if (p) this.setState({ progress: { ...p, rows: p.rows.map((y) => (y.number === r.number ? { ...y, title: x.data.title } : y)) } });
      }).catch(() => {});
    }
    this.setState({ progress: merged });
  }

  slug(s = this.state) {
    const hit = s.repos.find((r) => r.value === s.repo || (s.manual && r.path === s.path));
    return (hit && hit.value) || (s.manual ? '' : s.repo);
  }

  view(s = this.state) {
    const at = STEPS.findIndex((x) => x.key === stepFromState(this.fields(s)));
    const runStep = this.running(s) ? sessionStep(s.meta?.command) || STEPS[at].key : null;
    return sideView({ view: s.view, at, runStep, folder: s.folder, prd: s.prd });
  }

  input(step) {
    const id = `flow-${step.key}`;
    const field = { dump: 'text', prd: 'folder', issues: 'prd', dispatch: 'issues' }[step.key];
    const prose = step.key === 'dump';
    const Tag = prose ? 'textarea' : 'input';
    return html`<label for=${id}>${step.input}</label>
      <${Tag} id=${id} class=${prose ? 'field flow-prose' : 'field mono'} rows=${prose ? 6 : undefined} type=${prose ? undefined : 'text'}
        placeholder=${step.placeholder} aria-describedby=${this.state.why ? 'flow-why' : undefined} aria-invalid=${this.state.why ? 'true' : undefined}
        value=${this.state[field]} disabled=${this.running()} onInput=${(e) => this.setState({ [field]: e.target.value })} />
      ${this.state.why && html`<p id="flow-why" role="alert" class="error">${this.state.why}</p>`}`;
  }

  dispatched = () => {
    if (this.state.id) api('POST', `/api/flows/${encodeURIComponent(this.state.id)}/update`, { dispatched: true }).catch(() => {});
  };

  side(st, at, waiting, ask) {
    if (waiting && st.wide) return { cls: 'flow-side flow-ask', body: html`<h2 id="flow-side-h" class="flow-ask-h">${STEPS[at].label} needs your answer</h2>${ask}` };
    const v = this.view(st);
    if (!v) return null;
    const slug = this.slug(st);
    const issuesDone = !(this.running(st) && sessionStep(st.meta?.command) === 'issues');
    const title = (st.folder || st.prd || '').replace(/\/PRD\.md$/i, '').split('/').filter(Boolean).pop() || 'this flow';
    const body = v.kind === 'filing'
      ? html`<article class="flow-doc"><div class="flow-doc-head"><div><h2>Filing your idea</h2><p class="note" role="status">Dump is choosing the project and feature folder.</p></div></div>
          <blockquote class="flow-sent">${st.text}</blockquote></article>`
      : v.kind === 'note'
        ? html`<${NotePane} path=${v.path} stale=${v.stale} version=${`${st.sid}:${st.lastSid || ''}`} />`
        : html`<${IssueRows} title=${title} progress=${st.progress} slug=${slug} sessionDone=${issuesDone} />`;
    return { cls: 'flow-side', body };
  }

  render(_, st) {
    const { sid, meta, busy, folder, why, loaded, missing, id } = st;
    if (missing) return html`<div class="flow"><h1>Flow not found</h1><p>This flow doesn't exist on this aiw server. <a href="#/flow/new">Start a new flow</a></p></div>`;
    if (!loaded) return html`<div class="flow"><h1>Flow</h1><p role="status" class="note">Loading…</p></div>`;
    const at = STEPS.findIndex((s) => s.key === stepFromState(this.fields(st)));
    const issues = issueNumbers(st.issues);
    const waiting = meta && meta.outcome === 'waiting';
    const ask = waiting && html`<${Answer} key=${`${sid}:${(meta.pending_question || {}).id}`} session=${sid}
      onSent=${() => this.setState({ meta: { ...meta, outcome: 'running' } })} />`;
    const side = this.side(st, at, waiting, ask);
    const current = this.view(st);
    return html`<div class=${side ? 'flow flow--side' : 'flow'}>
      <div class="flow-main">
      <div class="flow-top">
        <h1>Flow</h1>
        <div class="flow-actions">
          <${FlowSwitcher} current=${id} />
          <a class="btn" href="#/flow/new">New flow</a>
        </div>
      </div>
      <p class="note">Turn a raw idea into dispatched issue runs. Each step stops for you only when it has a question.</p>
      <label for="flow-repo">Repo</label>
      ${this.combo.render(st, { id: 'flow-repo', error: why === 'Pick a repo first.' ? 'flow-why' : null })}
      <ol class="flow-steps">
        ${STEPS.map((step, i) => {
          const state = i < at ? (step.key === 'prd' && !folder ? 'skipped' : 'done') : i === at ? 'active' : 'locked';
          const shown = side && current && (current.kind === 'issues' ? ['issues', 'dispatch'].includes(step.key) && state === 'done' : st.view === step.key);
          return html`<li class=${`flow-step flow-${state}`} aria-current=${state === 'active' ? 'step' : undefined}>
            <span class="flow-mark" aria-hidden="true">${state === 'done' ? '✓' : i + 1}</span>
            <div class="flow-body">
              <h2 class="flow-name">${state === 'done'
                ? html`<button type="button" class="flow-name-btn" aria-pressed=${shown ? 'true' : 'false'} title="Show this step's output"
                    onClick=${() => this.setState({ view: st.view === step.key ? null : step.key })}>${step.label}</button>`
                : step.label} <span class="sr-only">(${STATE_TEXT[state]})</span>${state === 'skipped' && html` <span class="flow-tag">Skipped</span>`}</h2>
              ${state !== 'done' && html`<p class="note">${step.produces}</p>`}
              ${state === 'active' && step.key !== 'dispatch' && html`
                ${this.input(step)}
                ${sid ? html`<p class="note" role="status">${waiting ? 'Session waiting for your answer' : `Session ${meta ? meta.outcome : 'starting'}`} · <a href=${`#/session/${encodeURIComponent(sid)}`}>Open session</a></p>` : null}
                ${!st.wide && ask}
                ${meta && meta.outcome !== 'done' && TERMINAL.includes(meta.outcome) && meta.resume_command && html`<p class="note">Continue in terminal: <code>${meta.resume_command}</code></p>`}
                ${!waiting && html`<button type="button" class="primary" disabled=${busy || this.running()} onClick=${() => this.start(step)}>${sid ? `${step.action} again` : step.action}</button>`}`}
              ${state === 'active' && step.key === 'dispatch' && html`
                ${this.input(step)}
                ${issues.length ? html`<a class="btn btn--primary" href=${dispatchHref(issues)} onClick=${this.dispatched}>Open Dispatch with ${issues.join(', ')}</a>` : null}`}
              ${state === 'done' && html`<p class="note mono">${{ dump: folder || st.prd, prd: st.prd, issues: issues.join(', ') }[step.key]}</p>`}
            </div>
          </li>`;
        })}
      </ol>
      </div>
      ${side && html`<aside class=${`${side.cls} panel`} aria-labelledby=${waiting && st.wide ? 'flow-side-h' : undefined} aria-label=${waiting && st.wide ? undefined : "Step output"}>${side.body}</aside>`}
    </div>`;
  }
}
