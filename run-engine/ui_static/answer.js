import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { toast } from './toast.js';
import { mdToHtml } from './run.js';
import { loadFlow } from './flowstore.js';

const html = htm.bind(h);
const MAX_OTHER = 4000;
const REC_SUFFIX = ' (Recommended)';

export function viewMode(s) {
  if (!s) return 'state';
  const p = s.pending_question;
  if (s.waiting === true && s.outcome === 'waiting' && p && typeof p === 'object' && p.status === 'pending') return 'form';
  return s.outcome === 'failed' ? 'failed' : 'state';
}

export function displayLabel(label) {
  const l = String(label);
  return l.endsWith(REC_SUFFIX) ? l.slice(0, -REC_SUFFIX.length) : l;
}

export function initialAnswers(pending) {
  return (pending.questions || []).map((q) => ({ labels: q.recommended ? [q.recommended] : [], other: '' }));
}

export function toggle(state, i, label, multi) {
  const cur = state.answers[i].labels;
  let labels;
  if (!multi) labels = [label];
  else labels = cur.includes(label) ? cur.filter((l) => l !== label) : [...cur, label];
  const answers = state.answers.map((a, j) => (j === i ? { ...a, labels } : a));
  return { ...state, answers };
}

export function buildBody(pending, state) {
  const answers = {};
  for (let i = 0; i < pending.questions.length; i++) {
    const q = pending.questions[i];
    const a = state.answers[i] || { labels: [], other: '' };
    const other = q.allowFreeText ? String(a.other || '').trim() : '';
    const name = q.question || q.header || `Question ${i + 1}`;
    if (other) {
      if (other.length > MAX_OTHER) return { error: `Answer to "${name}" is longer than ${MAX_OTHER} characters` };
      answers[String(i)] = { other };
    } else if (a.labels.length) {
      answers[String(i)] = { labels: [...a.labels] };
    } else {
      return { error: `Please answer "${name}"` };
    }
  }
  return { round_id: pending.id, answers };
}

export function startSubmit(state) {
  return state.sending ? null : { ...state, sending: true, error: null };
}

export function runLink(session) {
  const l = session && session.link;
  return l && l.owner && l.repo && Number.isInteger(l.issue) && l.issue >= 1 ? { owner: l.owner, repo: l.repo, n: l.issue } : null;
}

export function runHash(session) {
  const l = runLink(session);
  return l ? `#/run/${encodeURIComponent(l.owner)}/${encodeURIComponent(l.repo)}/${l.n}` : '#/sessions';
}

// Where answering lands: the run for /run-issue, Flow when the saved flow is waiting on this
// session, otherwise the session itself (its transcript shows the answer being picked up).
export function doneHash(session, flow = loadFlow(globalThis.localStorage)) {
  if (runLink(session)) return runHash(session);
  if (session && session.id && flow && flow.sid === session.id) return '#/flow';
  return session && session.id ? `#/session/${encodeURIComponent(session.id)}` : '#/sessions';
}

export function afterSubmit(state, res, session) {
  if (res.ok) return { navigate: doneHash(session) };
  const err = res.data && typeof res.data.error === 'string' && res.data.error;
  return { ...state, sending: false, stale: res.status === 409, error: err || 'Could not reach the server or it returned an error' };
}

export async function submitAnswer(sid, body) {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(sid)}/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = null;
    }
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 0, data: null };
  }
}

export function planRun(session, pending) {
  const l = runLink(session);
  if (!l) return null;
  if (!/^\/(?:[\w.-]+:)?run-issue(?:\s|$)/.test(String(session.command || ''))) return null;
  const approve = (pending.questions || []).some((q) => (q.options || []).some((o) => String(o.label).startsWith('Approve')));
  return approve ? l : null;
}

export function planText(data) {
  return data && typeof data.plan === 'string' && data.plan ? data.plan : null;
}

export function resumeCommand(session) {
  if (!session || !session.session_id) return null;
  return `cd '${String(session.repo || '').replace(/'/g, "'\\''")}' && claude --resume '${String(session.session_id).replace(/'/g, "'\\''")}'`;
}

async function getJson(url) {
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  return { status: res.status, data: res.ok ? await res.json() : null };
}

export class Answer extends Component {
  state = { loaded: false, notFound: false, loadError: false, session: null, plan: null, form: null, copied: null };

  componentDidMount() {
    this.load();
  }

  async load() {
    const sid = this.props.session;
    let r;
    try {
      r = await getJson(`/api/sessions/${encodeURIComponent(sid)}`);
    } catch {
      r = { status: 0, data: null };
    }
    if (this.gone) return;
    if (r.status === 404) return this.setState({ loaded: true, notFound: true, loadError: false });
    if (!r.data) return this.setState({ loaded: true, notFound: false, loadError: true });
    const session = r.data;
    const pending = session.pending_question;
    const form = viewMode(session) === 'form' ? { answers: initialAnswers(pending), sending: false, error: null } : null;
    this.setState({ loaded: true, notFound: false, loadError: false, session, form });
    const pr = form && planRun(session, pending);
    if (!pr) return;
    try {
      const p = await getJson(`/api/runs/${encodeURIComponent(pr.owner)}/${encodeURIComponent(pr.repo)}/${pr.n}`);
      if (!this.gone) this.setState({ plan: planText(p.data) });
    } catch {
      // no plan panel when the run endpoint is absent or unreachable
    }
  }

  componentWillUnmount() {
    this.gone = true;
  }

  setOther(i, other) {
    const answers = this.state.form.answers.map((a, j) => (j === i ? { ...a, other } : a));
    this.setState({ form: { ...this.state.form, answers } });
  }

  pick(i, label, multi) {
    this.setState({ form: toggle(this.state.form, i, label, multi) });
  }

  submit = async (e) => {
    e.preventDefault();
    const { session, form } = this.state;
    const pending = session.pending_question;
    const body = buildBody(pending, form);
    if (body.error) return this.setState({ form: { ...form, error: body.error } });
    const started = startSubmit(form);
    if (!started) return;
    this.setState({ form: started });
    const res = await submitAnswer(this.props.session, body);
    if (this.gone) return;
    const next = afterSubmit(started, res, session);
    if (next.navigate) {
      toast('Answer sent, session resuming');
      // Embedded in Flow's step there is nowhere to go: the step keeps watching the session.
      if (this.props.onSent) this.props.onSent();
      else location.hash = next.navigate;
    }
    else this.setState({ form: next });
  };

  copy = async (cmd) => {
    try {
      await navigator.clipboard.writeText(cmd);
      this.setState({ copied: 'Copied' });
    } catch {
      this.setState({ copied: 'Copy failed — select the command above' });
    }
  };

  renderQuestion(q, i, a, sending, solo) {
    const multi = q.multiSelect === true;
    return html`
      <fieldset key=${i} class=${solo ? 'solo' : ''}>
        <legend>${q.question || q.header || `Question ${i + 1}`}</legend>
        ${(q.options || []).map((o) => html`
          <label class="opt">
            <input type=${multi ? 'checkbox' : 'radio'} name=${'q' + i} checked=${a.labels.includes(o.label)}
              disabled=${sending} onChange=${() => this.pick(i, o.label, multi)} />
            <span>${displayLabel(o.label)}
              ${o.label === q.recommended ? html` <span class="tag">recommended</span>` : null}
              ${o.description ? html`<small>${o.description}</small>` : null}</span>
          </label>`)}
        ${q.allowFreeText ? html`
          <label class="own">Or write your own answer (replaces the choice above)
            <textarea maxlength="4000" value=${a.other} disabled=${sending}
              onInput=${(e) => this.setOther(i, e.target.value)}></textarea>
          </label>` : null}
      </fieldset>`;
  }

  renderForm(session, form, embedded, plan, where) {
    const qs = session.pending_question.questions;
    const n = qs.length;
    return html`
          <form class=${embedded ? 'answer-form answer-inline' : 'panel answer-form'} onSubmit=${this.submit}>
            ${!embedded && html`<div class="waiting-line"><span class="dot"></span>Waiting on you${session.ended_at ? ' · no process running' : ''}</div>`}
            ${plan || embedded ? null : html`<div><div class="mono muted">${where} · ${String(session.command || '')}</div><h1>${n > 1 ? `${n} questions, answered together` : 'Answer needed'}</h1></div>`}
            ${qs.map((q, i) => this.renderQuestion(q, i, form.answers[i], form.sending, n === 1))}
            <button type="submit" class="btn--primary" disabled=${form.sending}>${form.sending ? 'Sending' : n > 1 ? `Submit all ${n} and resume` : 'Submit and resume session'}</button>
            ${form.error ? html`<p role="alert">${form.stale ? html`<strong>Already answered.</strong> ` : null}${form.error}</p>` : null}
            ${form.stale ? html`<button type="button" onClick=${() => this.load()}>Reload question</button>` : null}
            ${!embedded && session.session_id ? html`<p class="muted fine">Resumes with <span class="mono">--resume ${String(session.session_id).slice(0, 8)}…</span>. If that session is gone, run-issue re-enters from the Ledger.</p>` : null}
          </form>`;
  }

  render(_, { loaded, notFound, loadError, session, plan, form, copied }) {
    if (this.props.onSent) return loaded && session && viewMode(session) === 'form' ? this.renderForm(session, form, true) : null;
    if (!loaded) return html`<h1>Answer</h1><p role="status">Loading</p>`;
    if (notFound) return html`<h1>Answer</h1><p>Session not found. <a href="#/sessions">Back to sessions</a></p>`;
    if (loadError) return html`<h1>Answer</h1><p role="alert">Could not load the session.</p><button type="button" onClick=${() => this.load()}>Retry</button>`;
    const mode = viewMode(session);
    const link = runLink(session);
    const where = link ? `${link.repo} #${link.n}` : String(session.repo || '').split('/').pop();
    if (mode === 'form') {
      return html`
        <div class="answer">
          ${plan ? html`
            <section class="panel answer-context" aria-label="Plan">
              <div class="mono muted">${where} · ${String(session.command || '')}</div>
              <h1>Plan: test plan + implementation plan</h1>
              <div class="md plan-md" dangerouslySetInnerHTML=${{ __html: mdToHtml(plan) }}></div>
              ${link ? html`<a href=${runHash(session)}>Open run detail</a>` : null}
            </section>` : null}
          ${this.renderForm(session, form, false, plan, where)}
        </div>`;
    }
    if (mode === 'failed') {
      const cmd = resumeCommand(session);
      return html`
        <section class="panel answer-failed">
          <h1>Session failed</h1>
          <p>This session failed.</p>
          ${session.error ? html`<p role="alert">${String(session.error)}</p>` : null}
          ${cmd ? html`
            <p><code>${cmd}</code></p>
            <button type="button" onClick=${() => this.copy(cmd)}>Continue in terminal</button>
            ${copied ? html`<p role="status">${copied}</p>` : null}` : null}
        </section>`;
    }
    return html`<section class="panel answer-failed"><h1>Nothing to answer</h1><p>This session is ${session.outcome || 'not waiting'}; nothing to answer. <a href=${doneHash(session)}>Continue</a></p></section>`;
  }
}
