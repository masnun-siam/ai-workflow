import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { poll } from './app.js';
import { buildBody, loadLastRepo } from './launcher.js';
import { issueNumbers } from './dispatch.js';

const html = htm.bind(h);

// Guided Flow (#190): Dump → PRD → Issues → Dispatch. Each step runs its command as a headless
// session; its final `→ next:` line pre-fills the next step. All state lives in the hash.
const STEPS = [
  { key: 'dump', label: 'Dump', command: 'dump', input: 'Raw input: a feature idea, change, bug or task' },
  { key: 'prd', label: 'PRD', command: 'prd', input: 'Feature folder (05-Work/<Project>/<Feature>)' },
  { key: 'issues', label: 'Issues', command: 'gh-issue', input: 'PRD path, or the Bugs.md / Tasks.md note' },
  { key: 'dispatch', label: 'Dispatch', input: 'Issue numbers' },
];
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

export class Flow extends Component {
  constructor(props) {
    super(props);
    const p = props.route.params;
    this.state = { repo: p.repo || loadLastRepo(globalThis.localStorage) || '', repos: [], text: '', folder: p.folder, prd: p.prd,
      issues: p.issues.join(' '), sid: p.sid, meta: null, why: null, busy: false };
  }

  componentDidMount() {
    fetch('/api/repos', { headers: { Accept: 'application/json' } }).then((r) => (r.ok ? r.json() : null)).then((b) => {
      const repos = ((b && b.repos) || []).filter((r) => r && r.slug);
      this.setState({ repos, repo: this.state.repo || (repos[0] || {}).slug || '' });
    }).catch(() => {});
    if (this.state.sid) this.watch(this.state.sid);
  }

  componentWillUnmount() { this.gone = true; if (this.stop) this.stop(); }

  fields = (s = this.state) => ({ repo: s.repo, folder: s.folder, prd: s.prd, issues: issueNumbers(s.issues), sid: s.sid });

  save(patch) {
    this.setState(patch, () => history.replaceState(null, '', flowHash(this.fields())));
  }

  start = async (step) => {
    const { repo, text, folder, prd } = this.state;
    const args = { dump: text, prd: folder, issues: prd }[step.key].trim();
    if (!repo || !args) { this.setState({ why: !repo ? 'Pick a repo first.' : 'Fill in the input first.' }); return; }
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
    const step = stepFromState(this.fields());
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
    const Tag = step.key === 'dump' ? 'textarea' : 'input';
    return html`<label for=${id}>${step.input}</label>
      <${Tag} id=${id} class="field mono" rows=${step.key === 'dump' ? 4 : undefined} type=${step.key === 'dump' ? undefined : 'text'}
        value=${this.state[field]} disabled=${this.running()} onInput=${(e) => (field === 'text' ? this.setState({ text: e.target.value }) : this.save({ [field]: e.target.value }))} />`;
  }

  render(_, { repo, repos, sid, meta, why, busy }) {
    const cur = stepFromState(this.fields());
    const at = STEPS.findIndex((s) => s.key === cur);
    const issues = issueNumbers(this.state.issues);
    const waiting = meta && meta.outcome === 'waiting';
    return html`
      <h1>Flow</h1>
      <p class="note">Take one feature from a raw idea to dispatched runs: Dump → PRD → Issues → Dispatch. Each step stops for you.</p>
      <label for="flow-repo">Repo</label>
      <select id="flow-repo" class="field" value=${repo} onChange=${(e) => this.save({ repo: e.target.value })}>
        ${repo && !repos.some((r) => r.slug === repo) && html`<option value=${repo}>${repo}</option>`}
        ${repos.map((r) => html`<option value=${r.slug}>${r.slug}</option>`)}
      </select>
      <ol class="flow-steps">
        ${STEPS.map((step, i) => {
          const state = i < at ? (step.key === 'prd' && !this.state.folder ? 'skipped' : 'done') : i === at ? 'active' : 'locked';
          return html`<li class=${`panel flow-step flow-${state}`} aria-current=${state === 'active' ? 'step' : undefined}>
            <div class="flow-head"><span class="flow-name">${i + 1}. ${step.label}</span><span class=${`chip flow-chip-${state}`}>${{ done: 'Done', skipped: 'Skipped', active: 'Current', locked: 'Locked' }[state]}</span></div>
            ${state === 'locked' && html`<p class="note">Unlocks when ${STEPS[i - 1].label} hands off.</p>`}
            ${state === 'active' && step.key !== 'dispatch' && html`
              ${this.input(step)}
              ${sid ? html`<p class="note" role="status">Session ${meta ? meta.outcome : 'starting'}${waiting ? html` · <a href=${`#/answer/${encodeURIComponent(sid)}`}>Answer its question</a>` : ''} · <a href=${`#/session/${encodeURIComponent(sid)}`}>Open session</a></p>` : null}
              ${meta && meta.outcome !== 'done' && TERMINAL.includes(meta.outcome) && meta.resume_command && html`<p class="note">Continue in terminal: <code>${meta.resume_command}</code></p>`}
              <button type="button" class="primary" disabled=${busy || this.running()} onClick=${() => this.start(step)}>${sid ? 'Run again' : `Run ${step.command}`}</button>`}
            ${state === 'active' && step.key === 'dispatch' && html`
              ${this.input(step)}
              ${issues.length ? html`<a class="btn btn--primary" href=${dispatchHref(issues)}>Open Dispatch with ${issues.join(', ')}</a>` : null}`}
            ${state === 'done' && html`<p class="note mono">${{ dump: this.state.folder || this.state.prd, prd: this.state.prd, issues: issues.join(', ') }[step.key]}</p>`}
            ${state === 'active' && why && html`<p role="alert" class="error">${why}</p>`}
          </li>`;
        })}
      </ol>
      <p><a href=${flowHash({ repo })}>Start over</a></p>`;
  }
}
