import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { poll } from './app.js';

const html = htm.bind(h);

// Hooks are not vendored, so RunDetail is a class component and everything else is a pure helper.

// Mirrors ui_runner._issue_key (anchored, leading slash); /api/sessions is newest first, so the first match wins.
export function sessionForRun(sessions, owner, repo, n) {
  if (!Array.isArray(sessions)) return null;
  const slug = `${owner}/${repo}`;
  return (
    sessions.find((s) => {
      if (!s || s.repo !== slug) return false;
      if (typeof s.link === 'string' && s.link.endsWith(`/${slug}/issues/${n}`)) return true;
      const cmd = /^\/(?:[\w-]+:)?run-issue\s+(.*)/.exec(String(s.command || ''));
      const num = cmd && /(?:^|\s|\/issues\/)#?(\d+)(?=\s|$)/.exec(cmd[1]);
      return !!num && Number(num[1]) === n;
    }) || null
  );
}

export function actionsFor(session) {
  if (!session) return [];
  const out = [];
  if (['starting', 'running', 'waiting'].includes(session.outcome)) out.push('stop');
  if (session.outcome === 'stopped') out.push('resume');
  if (session.resume_command) out.push('terminal');
  return out;
}

// Drops responses whose offset is not past ours, so overlapping polls never duplicate events.
export function mergeStream(state, resp) {
  if (!resp || !Array.isArray(resp.events) || !(resp.offset > state.offset)) return state;
  return { events: state.events.concat(resp.events), offset: resp.offset };
}

export function totals(events, session) {
  const results = (events || []).filter((e) => e && e.kind === 'result');
  const costed = results.filter((e) => typeof e.cost === 'number').at(-1);
  const cost = costed ? costed.cost : typeof session?.cost === 'number' ? session.cost : null;
  const u = results.at(-1)?.usage;
  const tokens = u && typeof u.input === 'number' && typeof u.output === 'number' ? { input: u.input, output: u.output } : null;
  return { cost, tokens };
}

export function nearBottom(el) {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= 24;
}

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

function inline(s) {
  return s
    .split(/(`[^`]+`)/)
    .map((p, i) => (i % 2 ? `<code>${p.slice(1, -1)}</code>` : p.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')))
    .join('');
}

// Escape first, then transform: every tag in the output is one we emit here. No links on purpose.
export function mdToHtml(md) {
  if (!md) return '';
  const out = [];
  let para = [];
  let list = null; // 'ul' | 'ol'
  let fence = null;
  const flush = () => {
    if (para.length) out.push(`<p>${inline(para.join(' '))}</p>`);
    para = [];
    if (list) out.push(`</${list}>`);
    list = null;
  };
  for (const line of esc(String(md)).split('\n')) {
    if (fence) {
      if (/^\s*```/.test(line)) {
        out.push(`<pre><code>${fence.join('\n')}</code></pre>`);
        fence = null;
      } else fence.push(line);
      continue;
    }
    let m;
    if (/^\s*```/.test(line)) {
      flush();
      fence = [];
    } else if ((m = /^(#{1,6})\s+(.*)$/.exec(line))) {
      flush();
      out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`);
    } else if ((m = /^\s*(?:([-*])|\d+\.)\s+(.*)$/.exec(line))) {
      const kind = m[1] ? 'ul' : 'ol';
      if (list !== kind) {
        flush();
        out.push(`<${kind}>`);
        list = kind;
      }
      out.push(`<li>${inline(m[2])}</li>`);
    } else if (!line.trim()) flush();
    else {
      if (list) flush();
      para.push(line.trim());
    }
  }
  if (fence) out.push(`<pre><code>${fence.join('\n')}</code></pre>`);
  flush();
  return out.join('\n');
}

export async function copyCommand(text, nav = globalThis.navigator) {
  try {
    await nav.clipboard.writeText(text);
    return { ok: true };
  } catch {
    return { ok: false };
  }
}

export async function postAction(id, action) {
  try {
    const res = await fetch(`/api/sessions/${encodeURIComponent(id)}/${action}`, { method: 'POST' });
    if (res.ok) return { ok: true };
    let error = `HTTP ${res.status}`;
    try {
      error = (await res.json()).error || error;
    } catch {
      // non-JSON error body: keep the HTTP status text
    }
    return { ok: false, error };
  } catch (e) {
    return { ok: false, error: String(e?.message || e) };
  }
}

const KNOWN = ['done', 'running', 'escalated', 'bounced', 'pending'];
const money = (c) => (typeof c === 'number' ? `$${c.toFixed(2)}` : '—');

function Event({ e }) {
  if (e.kind === 'text') return html`<p class="ev">${e.text}</p>`;
  if (e.kind === 'tool') return html`<p class="ev tool">${`${e.name} ${e.input === undefined ? '' : JSON.stringify(e.input)}`}</p>`;
  if (e.kind === 'result') return html`<p class=${e.is_error ? 'ev result error' : 'ev result'}>${e.text}</p>`;
  return null;
}

export class RunDetail extends Component {
  state = { run: null, notFound: false, retry: false, stream: { events: [], offset: 0 }, tab: 'output', busy: null, msg: '', fallback: false };
  stream = { events: [], offset: 0 }; // authoritative copy: setState is async, poll URLs must see the latest offset
  follow = true;
  sid = null;
  live = null;

  componentDidMount() {
    const { owner, repo, n } = this.props;
    this.stopRun = poll(`/api/runs/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${n}`, 3000, (r) => {
      if (r.ok) this.setState({ run: r.data, notFound: false, retry: false });
      else if (r.status === 404) this.setState({ notFound: true, retry: false });
      else this.setState({ retry: true });
    });
    this.sync();
  }

  componentDidUpdate() {
    this.sync();
    if (this.follow && this.outEl) this.outEl.scrollTop = this.outEl.scrollHeight;
  }

  componentWillUnmount() {
    this.sid = null;
    if (this.stopRun) this.stopRun();
    if (this.stopStream) this.stopStream();
  }

  session() {
    const { owner, repo, n, sessions } = this.props;
    return sessionForRun(sessions, owner, repo, n);
  }

  take = (id) => (r) => {
    if (!r.ok || this.sid !== id) return;
    const next = mergeStream(this.stream, r.data);
    if (next === this.stream) return;
    this.stream = next;
    this.setState({ stream: this.stream });
  };

  // Idempotent: runs on every update, acts only when the session id or its liveness changed.
  sync() {
    const s = this.session();
    const id = s ? s.id : null;
    if (id !== this.sid) {
      if (this.stopStream) this.stopStream();
      this.stopStream = null;
      this.sid = id;
      this.live = null;
      this.stream = { events: [], offset: 0 };
      this.setState({ stream: this.stream, msg: '', fallback: false });
    }
    if (!id) return;
    const live = s.outcome === 'starting' || s.outcome === 'running';
    if (live === this.live) return;
    this.live = live;
    if (this.stopStream) this.stopStream();
    this.stopStream = null;
    const url = () => `/api/sessions/${encodeURIComponent(id)}/stream?offset=${this.stream.offset}`;
    if (live) this.stopStream = poll(url, 1000, this.take(id));
    else this.finalFetch(id, url);
  }

  // One last read from the saved offset picks up lines written after the final poll tick.
  async finalFetch(id, url) {
    let r;
    try {
      const res = await fetch(url(), { headers: { Accept: 'application/json' } });
      r = res.ok ? { ok: true, data: await res.json() } : { ok: false };
    } catch {
      r = { ok: false };
    }
    this.take(id)(r);
  }

  act = (action, label) => async (e) => {
    e?.preventDefault?.();
    const id = this.sid;
    this.setState({ busy: action, msg: '' });
    const r = await postAction(id, action);
    this.setState({ busy: null, msg: r.ok ? label : `${action === 'stop' ? 'Stop' : 'Resume'} failed: ${r.error}` });
  };

  terminal = async (e) => {
    e?.preventDefault?.();
    const r = await copyCommand(this.session()?.resume_command);
    this.setState({ msg: r.ok ? 'Copied' : 'Copy failed: select the command below', fallback: !r.ok });
  };

  onScroll = (e) => {
    this.follow = nearBottom(e.currentTarget);
  };

  selectBox = (el) => {
    if (el) {
      el.focus();
      el.select();
    }
  };

  setOut = (el) => {
    this.outEl = el;
  };

  render({ owner, repo, n, sessions }, { run, notFound, retry, stream, tab, busy, msg, fallback }) {
    if (notFound) return html`<h1>Run not found</h1><p><a href="#/">Back to Board</a></p>`;
    if (!run) return html`<h1>${`${owner}/${repo}#${n}`}</h1><p role="status">Loading…</p>`;
    const s = this.session();
    const acts = actionsFor(s);
    const t = totals(stream.events, s);
    const rt = run.totals || {};
    const stations = Array.isArray(run.stations) ? run.stations : [];
    const chip = (st) => `chip ${KNOWN.includes(st) ? st : 'other'}`;
    const TABS = [['output', 'Output'], ['plan', 'Plan']];

    let plan;
    if (tab !== 'plan') plan = null;
    else if (run.plan) plan = html`<div class="md" dangerouslySetInnerHTML=${{ __html: mdToHtml(run.plan) }}></div>`;
    else if (run.errors?.plan) plan = html`<p class="muted">Plan could not be read</p>`;
    else plan = html`<p class="muted">No plan yet</p>`;

    let output;
    if (!s) output = html`<p class="muted">${Array.isArray(sessions) ? 'No UI session for this run' : 'Loading…'}</p>`;
    else if (!stream.events.length) output = html`<p class="muted">No output yet</p>`;
    else output = stream.events.map((e, i) => html`<${Event} key=${i} e=${e} />`);

    return html`
      <section class="run">
        <div class="run-head">
          <h1>${`${owner}/${repo}#${n}`}</h1>
          <span class=${chip(run.status)}>${run.status}</span>
          ${retry && html`<span role="status" class="offline">Retrying…</span>`}
        </div>
        ${s && s.resumed_fresh && html`<p class="note">${`Resumed fresh${s.note ? `: ${s.note}` : ''}`}</p>`}
        ${acts.length > 0 && html`
          <div class="actions">
            ${acts.includes('stop') && html`<button type="button" disabled=${busy === 'stop'} onClick=${this.act('stop', 'Stopped')}>Stop</button>`}
            ${acts.includes('resume') && html`<button type="button" disabled=${busy === 'resume'} onClick=${this.act('resume', 'Resumed')}>Resume</button>`}
            ${acts.includes('terminal') && html`<button type="button" onClick=${this.terminal}>Continue in terminal</button>`}
          </div>`}
        ${run.errors?.ledger && html`<p class="muted">Ledger could not be read</p>`}
        <div role="status" class="msg">${msg}</div>
        ${fallback && s && html`<label class="cmd">Command <input readOnly value=${s.resume_command} aria-label="Resume command" ref=${this.selectBox} /></label>`}
        <div class="panel">
          <h2>Timeline</h2>
          <ol class="timeline">
            ${stations.map((st) => html`
              <li aria-current=${st.name === run.currentStation ? 'step' : undefined}>
                <span class="name">${st.name}</span>
                <span class=${chip(st.status)}>${st.status}</span>
                ${st.bounces > 0 && html`<span class="muted">${`${st.bounces} bounces`}</span>`}
              </li>`)}
          </ol>
          <p class="muted">${`${rt.stations ?? stations.length} stations, ${rt.done ?? 0} done, ${rt.bounces ?? 0} bounces`}</p>
          <p class="muted">${`Cost ${money(t.cost)}`}${t.tokens && `, ${t.tokens.input} in / ${t.tokens.output} out tokens`}</p>
        </div>
        <div class="panel">
          <div role="tablist" aria-label="Run detail">
            ${TABS.map(([k, label]) => html`
              <button type="button" role="tab" id=${`tab-${k}`} aria-controls="run-panel" aria-selected=${tab === k} onClick=${() => this.setState({ tab: k })}>${label}</button>`)}
          </div>
          <div role="tabpanel" id="run-panel" aria-labelledby=${`tab-${tab}`}>
            ${tab === 'plan' ? plan : html`<div class="output" ref=${this.setOut} onScroll=${this.onScroll}>${output}</div>`}
          </div>
        </div>
      </section>
    `;
  }
}
