import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { poll } from './app.js';
import { buildBody, loadLastRepo, repoCombo, repoOptions } from './launcher.js';
import { issueNumbers } from './dispatch.js';
import { Answer } from './answer.js';
import { loadFlow, saveFlow, clearFlow } from './flowstore.js';

const html = htm.bind(h);

// Guided Flow (#190): Dump → PRD → Issues → Dispatch. Each step runs its command as a headless
// session; its final `→ next:` line pre-fills the next step. All state lives in the hash.
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

export { loadFlow, saveFlow, clearFlow };

// Steps passed (done or skipped) for the nav progress bar, or null when there is no flow in
// progress. A typed-but-unrun draft is not progress: a step must have handed off or be running.
export function flowProgress(flow) {
  if (!flow) return null;
  const at = STEPS.findIndex((s) => s.key === stepFromState({ ...flow, issues: issueNumbers(flow.issues || '') }));
  return at > 0 || flow.sid ? { done: at, total: STEPS.length } : null;
}

// "Continue in Flow" for a session of one of the flow's commands: the flow reattaches to it and
// takes its handoff. Null for any other command.
export function flowLink(meta) {
  const m = /^\/(?:[\w-]+:)?(dump|prd|gh-issue)(\s|$)/.exec((meta && meta.command) || '');
  return m ? flowHash({ repo: meta.repo, sid: meta.id }) : null;
}

// Following that link replaces the saved flow, so ask first when the saved one has a finished step.
export function continueFlow(e, meta) {
  const storage = globalThis.localStorage;
  const saved = loadFlow(storage);
  const p = flowProgress(saved);
  if (p && p.done > 0 && saved.sid !== meta.id && !globalThis.confirm('Replace the flow in progress? Its folder, PRD and issue numbers are cleared.')) {
    e.preventDefault();
    return;
  }
  clearFlow(storage);
}

export class Flow extends Component {
  constructor(props) {
    super(props);
    const p = props.route.params;
    // A bare #/flow (the nav link) resumes the saved flow; a hash with values links to a specific one.
    const saved = loadFlow(globalThis.localStorage) || {};
    this.linked = !!(p.repo || p.folder || p.prd || p.issues.length || p.sid);
    const f = this.linked ? { ...p, issues: p.issues.join(' ') } : saved;
    // The repo is a registered slug or, like New run, an absolute path to a checkout.
    const repo = f.repo || loadLastRepo(globalThis.localStorage) || '';
    const manual = repo.startsWith('/');
    this.state = { repo: manual ? '' : repo, manual, path: manual ? repo : '', repos: [], canBrowse: false, repoQuery: null, repoOpen: false,
      repoActive: 0, browsing: false, text: saved.text || '', folder: f.folder || '', prd: f.prd || '', issues: f.issues || '', sid: f.sid || '',
      meta: null, why: null, busy: false };
  }

  persisted = (s = this.state) => ({ ...this.fields(s), issues: s.issues, text: s.text });

  componentDidUpdate(_, prev) {
    const a = JSON.stringify(this.persisted()), b = JSON.stringify(this.persisted(prev));
    if (a !== b && !this.gone) saveFlow(globalThis.localStorage, this.persisted());
  }

  combo = repoCombo(this, () => this.save({ why: null }));

  componentDidMount() {
    // Wide screens answer a session's question in a column beside the steps; narrow ones in the step.
    this.mq = globalThis.matchMedia?.('(min-width: 1200px)');
    if (this.mq) { this.onMq = () => this.setState({ wide: this.mq.matches }); this.mq.addEventListener('change', this.onMq); this.onMq(); }
    fetch('/api/repos', { headers: { Accept: 'application/json' } }).then((r) => (r.ok ? r.json() : null)).then((b) => {
      const repos = repoOptions(b);
      const { repo, manual, path } = this.state;
      // A checkout path that is a registered repo (a session's repo, say) shows as that repo.
      const known = manual && repos.find((r) => r.path === path);
      this.setState({ repos, canBrowse: !!b && b.can_browse === true, repo: known ? known.value : repo || manual ? repo : (repos[0] || {}).value || '',
        ...(known ? { manual: false, path: '' } : repos.length || manual ? {} : { manual: true, path: repo }) }, () => this.save({}));
    }).catch(() => {});
    // A link names the flow to work on: it becomes the saved flow right away, not on its first change.
    if (this.linked) saveFlow(globalThis.localStorage, this.persisted());
    else history.replaceState(null, '', flowHash(this.fields()));
    if (this.state.sid) this.watch(this.state.sid);
  }

  componentWillUnmount() { this.gone = true; if (this.stop) this.stop(); if (this.mq) this.mq.removeEventListener('change', this.onMq); }

  fields = (s = this.state) => ({ repo: (s.manual ? s.path : s.repo).trim(), folder: s.folder, prd: s.prd, issues: issueNumbers(s.issues), sid: s.sid });

  save(patch) {
    this.setState(patch, () => history.replaceState(null, '', flowHash(this.fields())));
  }

  start = async (step) => {
    const { text, folder, prd } = this.state;
    const { repo } = this.fields();
    const args = { dump: text, prd: folder, issues: prd }[step.key].trim();
    if (!repo || !args) { this.setState({ why: !repo ? 'Pick a repo first.' : 'Fill in the field above first.' }); return; }
    this.setState({ busy: true, why: null, meta: null });
    let res, data = null;
    try {
      res = await fetch('/api/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildBody({ repo, command: step.command, args })) });
      data = await res.json().catch(() => null);
    } catch {
      this.setState({ busy: false, why: 'Could not reach the aiw server.' });
      return;
    }
    if (res.status !== 201 || !data || !data.id) { this.setState({ busy: false, why: (data && data.error) || `Request failed (HTTP ${res.status})` }); return; }
    this.setState({ busy: false });
    this.save({ sid: data.id });
    this.watch(data.id);
  };

  // Poll the active session at the usual 3 s; once it ends, read its final result and hand off.
  watch(sid) {
    if (this.stop) this.stop();
    this.stop = poll(`/api/sessions/${encodeURIComponent(sid)}`, 3000, (r) => {
      if (!r.ok) { if (r.status === 404) { this.stop(); this.save({ sid: '', why: 'That session no longer exists.' }); } return; }
      this.setState({ meta: r.data });
      if (TERMINAL.includes(r.data.outcome)) { this.stop(); this.finish(sid, r.data); }
    });
  }

  async finish(sid, meta) {
    // The session's own command names the step it ran, so a session reattached from its page
    // ("Continue in Flow") hands off correctly even when the flow knew nothing before it.
    const cmd = (/^\/(?:[\w-]+:)?([\w-]+)/.exec(meta.command || '') || [])[1];
    const step = (STEPS.find((s) => s.command === cmd) || {}).key || stepFromState(this.fields());
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
    this.save({ ...out, sid: '', meta: null, why: null });
  }

  // A session is in flight: its step's input stays fixed so the handoff lands on the step that ran.
  running = () => !!this.state.sid && !(this.state.meta && TERMINAL.includes(this.state.meta.outcome));

  input(step) {
    const id = `flow-${step.key}`;
    const field = { dump: 'text', prd: 'folder', issues: 'prd', dispatch: 'issues' }[step.key];
    const prose = step.key === 'dump';
    const Tag = prose ? 'textarea' : 'input';
    return html`<label for=${id}>${step.input}</label>
      <${Tag} id=${id} class=${prose ? 'field flow-prose' : 'field mono'} rows=${prose ? 6 : undefined} type=${prose ? undefined : 'text'}
        placeholder=${step.placeholder} aria-describedby=${this.state.why ? 'flow-why' : undefined} aria-invalid=${this.state.why ? 'true' : undefined}
        value=${this.state[field]} disabled=${this.running()} onInput=${(e) => (field === 'text' ? this.setState({ text: e.target.value }) : this.save({ [field]: e.target.value }))} />
      ${this.state.why && html`<p id="flow-why" role="alert" class="error">${this.state.why}</p>`}`;
  }

  // Resetting drops every handed-off value, so ask once any step has produced one.
  startOver = (e) => {
    const { folder, prd, issues } = this.state;
    if ((folder || prd || issues) && !globalThis.confirm('Start over? The folder, PRD and issue numbers from this flow are cleared.')) e.preventDefault();
    else { this.gone = true; clearFlow(globalThis.localStorage); }
  };

  render(_, st) {
    const { sid, meta, busy, folder, prd, why } = st;
    const { repo } = this.fields(st);
    const cur = stepFromState(this.fields());
    const at = STEPS.findIndex((s) => s.key === cur);
    const issues = issueNumbers(this.state.issues);
    const waiting = meta && meta.outcome === 'waiting';
    const ask = waiting && html`<${Answer} key=${`${sid}:${(meta.pending_question || {}).id}`} session=${sid}
      onSent=${() => this.setState({ meta: { ...meta, outcome: 'running' } })} />`;
    const aside = ask && st.wide;
    return html`<div class=${aside ? 'flow flow--ask' : 'flow'}>
      <div class="flow-main">
      <div class="flow-top">
        <h1>Flow</h1>
        ${(folder || prd || issues.length || sid) && html`<a class="btn" href=${flowHash({ repo })} onClick=${this.startOver}>Start over</a>`}
      </div>
      <p class="note">Turn a raw idea into dispatched issue runs. You review each step's result before the next one starts.</p>
      <label for="flow-repo">Repo</label>
      ${this.combo.render(st, { id: 'flow-repo', error: why === 'Pick a repo first.' ? 'flow-why' : null })}
      <ol class="flow-steps">
        ${STEPS.map((step, i) => {
          const state = i < at ? (step.key === 'prd' && !folder ? 'skipped' : 'done') : i === at ? 'active' : 'locked';
          return html`<li class=${`flow-step flow-${state}`} aria-current=${state === 'active' ? 'step' : undefined}>
            <span class="flow-mark" aria-hidden="true">${state === 'done' ? '✓' : i + 1}</span>
            <div class="flow-body">
              <h2 class="flow-name">${step.label} <span class="sr-only">(${STATE_TEXT[state]})</span>${state === 'skipped' && html` <span class="flow-tag">Skipped</span>`}</h2>
              ${state !== 'done' && html`<p class="note">${step.produces}</p>`}
              ${state === 'active' && step.key !== 'dispatch' && html`
                ${this.input(step)}
                ${sid ? html`<p class="note" role="status">${waiting ? 'Session waiting for your answer' : `Session ${meta ? meta.outcome : 'starting'}`} · <a href=${`#/session/${encodeURIComponent(sid)}`}>Open session</a></p>` : null}
                ${!aside && ask}
                ${meta && meta.outcome !== 'done' && TERMINAL.includes(meta.outcome) && meta.resume_command && html`<p class="note">Continue in terminal: <code>${meta.resume_command}</code></p>`}
                ${!waiting && html`<button type="button" class="primary" disabled=${busy || this.running()} onClick=${() => this.start(step)}>${sid ? `${step.action} again` : step.action}</button>`}`}
              ${state === 'active' && step.key === 'dispatch' && html`
                ${this.input(step)}
                ${issues.length ? html`<a class="btn btn--primary" href=${dispatchHref(issues)} onClick=${() => { this.gone = true; clearFlow(globalThis.localStorage); }}>Open Dispatch with ${issues.join(', ')}</a>` : null}`}
              ${state === 'done' && html`<p class="note mono">${{ dump: folder || prd, prd, issues: issues.join(', ') }[step.key]}</p>`}
            </div>
          </li>`;
        })}
      </ol>
      </div>
      ${aside && html`<aside class="flow-ask panel" aria-labelledby="flow-ask-h">
        <h2 id="flow-ask-h">${STEPS[at].label} needs your answer</h2>
        ${ask}
      </aside>`}
    </div>`;
  }
}
