import { GhChips, FailingChecks, quiet } from './ghstatus.js';
import { IssueLink } from './issue.js';
import { PrLink } from './pr.js';
import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { poll } from './app.js';
import { formatWhen, grindLabel, toolSummary, sessionLabel } from './fmt.js';
import { toast } from './toast.js';
import { openCleanup } from './cleanup.js';
import { LimitBanner } from './limits.js';

const html = htm.bind(h);

// Hooks are not vendored, so RunDetail is a class component and everything else is a pure helper.

// Mirrors ui_runner._issue_key (anchored, leading slash).
function matchesRun(s, slug, n) {
  if (!s) return false;
  // Sessions started with a checkout path (dispatch pipelines) carry the issue only in the link object.
  if (s.link && typeof s.link === 'object') return `${s.link.owner}/${s.link.repo}` === slug && s.link.issue === n;
  if (s.repo !== slug) return false;
  if (typeof s.link === 'string' && s.link.endsWith(`/${slug}/issues/${n}`)) return true;
  const cmd = /^\/(?:[\w-]+:)?run-issue\s+(.*)/.exec(String(s.command || ''));
  const num = cmd && /(?:^|\s|\/issues\/)#?(\d+)(?=\s|$)/.exec(cmd[1]);
  return !!num && Number(num[1]) === n;
}

// /api/sessions is newest first, so the first match is the current session.
export function sessionsForRun(sessions, owner, repo, n) {
  return Array.isArray(sessions) ? sessions.filter((s) => matchesRun(s, `${owner}/${repo}`, n)) : [];
}

export function sessionForRun(sessions, owner, repo, n) {
  return sessionsForRun(sessions, owner, repo, n)[0] || null;
}

export function actionsFor(session) {
  if (!session) return [];
  const out = [];
  if (['starting', 'running', 'waiting', 'limited'].includes(session.outcome)) out.push('stop');
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

// Silent when every station finished cleanly: the list above already says so.
export function stationNote(rt, stations) {
  const total = rt.stations ?? stations.length;
  const done = rt.done ?? stations.filter((x) => x.status === 'done').length;
  const bounces = rt.bounces ?? 0;
  if (done < total) return `${done} of ${total} stations done${bounces ? `, ${bounces} bounce${bounces === 1 ? '' : 's'}` : ''}`;
  return bounces ? `${bounces} bounce${bounces === 1 ? '' : 's'}` : '';
}

const TAIL = 80; // events rendered before "Show earlier": a long run is thousands of nodes

export function nearBottom(el) {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= 24;
}

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

// Runs on already-escaped text, so it must not swallow an escaped quote or angle bracket.
const URL = /https?:\/\/(?:(?!&(?:quot|#39|gt|lt);)[^\s<])+/g;

function inline(s) {
  // Code spans are lifted out first so bold can wrap them (`**use `x` here**`) and nothing inside them is touched.
  const codes = [];
  const lifted = s.replace(/`([^`]+)`/g, (_, c) => `\u0000${codes.push(c) - 1}\u0000`);
  return lifted
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(URL, (u) => {
      const href = u.replace(/[.,;:!?)\]}]+$/, '');
      return `<a href="${href}" target="_blank" rel="noopener noreferrer">${href}</a>${u.slice(href.length)}`;
    })
    .replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[i]}</code>`);
}

// Escape first, then transform: every tag in the output is one we emit here. Only http(s) URLs become links.
export function mdToHtml(md) {
  if (!md) return '';
  const out = [];
  let para = [];
  let list = null; // 'ul' | 'ol' (outermost)
  let base = 0; // indent of the outermost list
  const nest = []; // open nested lists: [{ kind, indent }]
  let fence = null;
  const flush = () => {
    if (para.length) out.push(`<p>${inline(para.join(' '))}</p>`);
    para = [];
    while (nest.length) out.push(`</${nest.pop().kind}></li>`);
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
    } else if ((m = /^(\s*)(?:([-*])|\d+\.)\s+(.*)$/.exec(line))) {
      const kind = m[2] ? 'ul' : 'ol';
      const indent = m[1].length;
      if (list && !nest.length && kind !== list && indent <= base) flush();
      if (list && indent > (nest.length ? nest[nest.length - 1].indent : base) && out[out.length - 1].endsWith('</li>')) {
        out.push(out.pop().slice(0, -5), `<${kind}>`); // reopen the parent item around a nested list
        nest.push({ kind, indent });
      } else {
        while (nest.length && indent < nest[nest.length - 1].indent) out.push(`</${nest.pop().kind}></li>`);
        if (!list) {
          out.push(`<${kind}>`);
          list = kind;
          base = indent;
        }
      }
      out.push(`<li>${inline(m[3])}</li>`);
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

// What the "Skip CI for now" button tells a grind that paused on red CI.
export const SKIP_CI_REPLY = 'Skip CI for now, complete the grind, then come back and fix the CI';

// A grind paused because of CI (red head commit, Gate 2, a failing check), not because of a review decision.
export const pausedOnCi = (run) => !!run?.grind && run.grind.state === 'paused' && (run.gh?.pr?.ci === 'red' || /\b(ci|gate\s*2|checks?)\b/i.test(run.grind.reason || ''));

// A merged or closed PR has nothing left to review, so it never offers a grind.
export const canStartGrind = (run) => run?.status === 'done' && !!run.pr && !run.grind && !['MERGED', 'CLOSED'].includes(run.gh?.pr?.state);

export async function grindPost(owner, repo, issue, action, text) {
  try {
    const res = await fetch(`/api/grind/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ owner, repo, issue, ...(text ? { text } : {}) }) });
    const data = await res.json().catch(() => ({}));
    return res.ok ? { ok: true, state: data.state } : { ok: false, error: data.error || `HTTP ${res.status}` };
  } catch (e) {
    return { ok: false, error: String(e?.message || e) };
  }
}


export { sessionLabel };

const KNOWN = ['done', 'running', 'escalated', 'bounced', 'pending'];
const money = (c) => (typeof c === 'number' ? `$${c.toFixed(2)}` : '—');

// A turn's final result usually repeats the last message above it: show it once and mark the turn's end.
export function visibleEvents(events) {
  const out = [];
  for (const e of events || []) {
    const prev = out.at(-1);
    if (e.kind === 'result' && !e.is_error && prev && prev.kind === 'text' && String(prev.text).trim() === String(e.text).trim()) out.push({ kind: 'turn' });
    else out.push(e);
  }
  return out;
}

function Event({ e }) {
  if (e.kind === 'turn') return html`<hr class="ev turn" />`;
  if (e.kind === 'text') return html`<div class="ev ev-text md" dangerouslySetInnerHTML=${{ __html: mdToHtml(e.text) }}></div>`;
  if (e.kind === 'tool') return html`<p class="ev tool" title=${e.input === undefined ? '' : JSON.stringify(e.input, null, 2)}><span class="ev-name">${e.name}</span> ${toolSummary(e, 240)}</p>`;
  if (e.kind === 'result') return html`<div class=${`${e.is_error ? 'ev result error' : 'ev result'} ev-text md`} dangerouslySetInnerHTML=${{ __html: mdToHtml(e.text) }}></div>`;
  return null;
}

export class RunDetail extends Component {
  state = { run: null, notFound: false, retry: false, stream: { events: [], offset: 0 }, tab: 'output', busy: null, msg: '', fallback: false, promptText: '', replyText: '', behind: false, showAll: false };
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
    // waiting stays live until the claude process exits (ui_runner stamps ended_at only then).
    const live = ['starting', 'running'].includes(s.outcome) || (s.outcome === 'waiting' && !s.ended_at);
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
    if (action === 'stop' && !globalThis.confirm('Stop this run? The process is killed; the branch and worktree are kept and you can resume it.')) return;
    const id = this.sid;
    this.setState({ busy: action, msg: '' });
    const r = await postAction(id, action);
    const msg = r.ok ? label : `${action === 'stop' ? 'Stop' : 'Resume'} failed: ${r.error}`;
    this.setState({ busy: null, msg });
    toast(msg, r.ok ? 'ok' : 'error');
  };

  terminal = async (e) => {
    e?.preventDefault?.();
    const r = await copyCommand(this.session()?.resume_command);
    const msg = r.ok ? 'Copied' : 'Copy failed: select the command below';
    this.setState({ msg, fallback: !r.ok });
    toast(msg, r.ok ? 'ok' : 'error');
  };

  onScroll = (e) => {
    this.follow = nearBottom(e.currentTarget);
    if (this.state.behind === this.follow) this.setState({ behind: !this.follow });
  };

  jumpLatest = () => {
    this.follow = true;
    if (this.outEl) this.outEl.scrollTop = this.outEl.scrollHeight;
    this.setState({ behind: false });
  };

  selectBox = (el) => {
    if (el) {
      el.focus();
      el.select();
    }
  };

  releaseMainTree = async () => {
    const { owner, repo } = this.props;
    if (!globalThis.confirm('Release the main tree? The next waiting main-tree run starts in this checkout.')) return;
    this.setState({ busy: 'maintree' });
    const r = await fetch('/api/maintree/release', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ owner, repo }) })
      .then((x) => x.json()).catch(() => ({ error: 'request failed' }));
    this.setState({ busy: null, msg: r.error || (r.released ? 'Main tree released' : 'Nothing was holding the main tree') });
  };

  grind = async (action) => {
    const { owner, repo, n } = this.props;
    if (action === 'start' && !globalThis.confirm('Start review grinding? This posts a trigger message to the repo\'s Slack review channel.')) return;
    this.setState({ busy: 'grind' });
    const r = await grindPost(owner, repo, Number(n), action);
    this.setState({ busy: null, msg: r.ok ? ({ start: r.state === 'queued' ? 'Grind queued behind the running ones' : 'Grinding started', pause: 'Grind paused', resume: 'Grind resumed', 'rerun-ci': 'Failed CI jobs are rerunning' })[action] : r.error });
  };

  sendReply = async (text, clear) => {
    const { owner, repo, n } = this.props;
    this.setState({ busy: 'grind' });
    const r = await grindPost(owner, repo, Number(n), 'reply', text);
    this.setState({ busy: null, msg: r.ok ? 'Decision sent, the grind is resuming' : r.error, ...(r.ok && clear ? { replyText: '' } : {}) });
  };

  replyGrind = (e) => {
    e.preventDefault();
    const text = this.state.replyText.trim();
    if (text) this.sendReply(text, true);
  };

  skipCi = () => this.sendReply(SKIP_CI_REPLY, false);

  sendPrompt = async (e) => {
    e.preventDefault();
    const { owner, repo, n, sessions } = this.props;
    const target = sessionsForRun(sessions, owner, repo, n).find((x) => x.session_id);
    const text = this.state.promptText.trim();
    if (!target || !text || this.state.busy === 'prompt' || target.outcome === 'waiting') return;
    this.setState({ busy: 'prompt' });
    try {
      const res = await fetch(`/api/sessions/${encodeURIComponent(target.id)}/prompt`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
      const data = await res.json().catch(() => ({}));
      if (res.ok) this.setState({ promptText: '', msg: data.state === 'queued' ? 'Queued: it goes out when the session ends' : 'Prompt sent, the session is resuming' });
      else this.setState({ msg: data.error || `HTTP ${res.status}` });
    } catch (er) {
      this.setState({ msg: String(er?.message || er) });
    }
    this.setState({ busy: null });
  };

  setOut = (el) => {
    this.outEl = el;
  };

  render({ owner, repo, n, sessions }, { run, notFound, retry, stream, tab, busy, msg, fallback, promptText, replyText, behind, showAll }) {
    if (notFound) return html`<h1>Run not found</h1><p><a href="#/">Back to Board</a></p>`;
    if (!run) return html`<h1>${`${owner}/${repo}#${n}`}</h1><p role="status">Loading…</p>`;
    const s = this.session();
    const acts = actionsFor(s);
    const cleanable = run.status === 'done' || (s ? ['stopped', 'failed'].includes(s.outcome) : quiet(run.updated, run.status)) || run.gh?.pr?.state === 'MERGED';
    const t = totals(stream.events, s);
    const rt = run.totals || {};
    const stations = Array.isArray(run.stations) ? run.stations : [];
    const chip = (st) => `chip ${KNOWN.includes(st) ? st : 'other'}`;
    const all = sessionsForRun(sessions, owner, repo, n);
    const target = all.find((x) => x.session_id) || null;
    const TABS = [['output', 'Live output'], ['plan', 'Plan'], ['sessions', `Sessions (${all.length})`]];

    let plan;
    if (tab !== 'plan') plan = null;
    else if (run.plan) plan = html`<div class="md" dangerouslySetInnerHTML=${{ __html: mdToHtml(run.plan) }}></div>`;
    else if (run.errors?.plan) plan = html`<p class="muted">Plan could not be read</p>`;
    else plan = html`<p class="muted">No plan yet</p>`;

    let output;
    if (!s && Array.isArray(sessions) && run.log?.length) {
      output = html`<p class="muted">Started outside the UI: station results from the run's ledger.</p>
        <ol class="run-log">${run.log.map((e) => html`
          <li><span class="mono">${e.station}</span> <span class=${chip(e.status === 'passed' ? 'done' : e.status)}>${e.status}</span> ${e.summary}</li>`)}</ol>`;
    } else if (!s) output = html`<p class="muted">${Array.isArray(sessions) ? 'No UI session for this run' : 'Loading…'}</p>`;
    else if (!stream.events.length) output = html`<p class="muted">No output yet</p>`;
    else {
      const all = visibleEvents(stream.events);
      const hidden = showAll ? 0 : Math.max(0, all.length - TAIL);
      output = html`${hidden > 0 && html`<button type="button" class="btn btn-sm earlier" onClick=${() => this.setState({ showAll: true })}>Show ${hidden} earlier events</button>`}${all.slice(hidden).map((e, i) => html`<${Event} key=${i + hidden} e=${e} />`)}`;
    }

    let body;
    if (tab === 'plan') body = plan;
    else if (tab === 'sessions') {
      body = all.length
        ? html`<ul class="sessions-list">${all.map((x) => html`
            <li>
              <span class="mono">${sessionLabel(x.command)}</span>
              <span class=${`chip chip-${x.outcome}`}>${x.outcome}</span>
              <span class="muted">${formatWhen(x.started_at)}</span>
              <span class="mono muted">${money(x.cost)}</span>
              <a href=${`#/session/${encodeURIComponent(x.id)}`}>Transcript</a>
            </li>`)}</ul>`
        : html`<p class="muted">No UI sessions for this run</p>`;
    } else body = html`<div class="output-wrap">
      <div class="output" ref=${this.setOut} onScroll=${this.onScroll}>${output}${this.live && html`<div class="streaming"><span class="pulse"></span>streaming events…</div>`}</div>
      ${behind && html`<button type="button" class="btn btn-sm jump" onClick=${this.jumpLatest}>Jump to latest ↓</button>`}
    </div>`;

    return html`
      <section class="run">
        <div class="run-head run-head--run">
          <div class="run-title">
            <div class="run-meta run-meta--items">
              <span class="mono">${`${owner}/${repo}#${n}`}</span>
              ${s && html`<span>${String(s.command || '').replace(/^\/(?:[\w-]+:)?/, '').split(/\s/)[0] || 'run'}</span>`}
              ${s && html`<span class="mono" title="Session id">session ${String(s.id).slice(-8)}</span>`}
              ${s && s.claude_cmd && s.claude_cmd !== 'claude' && html`<span class="mono" title="Claude account">${s.claude_cmd}</span>`}
              <${IssueLink} owner=${owner} repo=${repo} issue=${n}>Issue<//>
              ${(run.pr || run.gh?.pr?.url) && html`<${PrLink} url=${run.pr || run.gh.pr.url}>PR${run.gh?.pr?.number ? ' #' + run.gh.pr.number : ''}<//>`}
              ${run.branch && html`<span class="run-branch mono" title=${run.branch}>${run.branch}</span>`}
            </div>
            <h1>${run.title || `Issue #${n}`}</h1>
            <div class="run-chips">
              <span class=${chip(run.status)}>${run.status}</span>
              ${run.status === 'done' && s && ['running', 'starting'].includes(s.outcome) && html`<span class="chip chip-running" title="The session is still working after the last station finished">session live</span>`}
              <${GhChips} gh=${run.gh} labels=${true} />
              ${retry && html`<span role="status" class="offline">Retrying…</span>`}
              ${run.grind && grindLabel(run.grind) && html`<span class=${'chip chip-grind-' + run.grind.state}>${grindLabel(run.grind)}</span>`}
            </div>
          </div>
          <div class="run-acts">
            ${acts.includes('stop') && html`<button type="button" class="btn btn--danger" disabled=${busy === 'stop'} onClick=${this.act('stop', 'Stopped')}>Stop</button>`}
            ${acts.includes('resume') && html`<button type="button" disabled=${busy === 'resume'} onClick=${this.act('resume', 'Resumed')}>Resume</button>`}
            ${acts.includes('terminal') && html`<button type="button" onClick=${this.terminal}>Continue in terminal</button>`}
            ${run.maintree && html`<span class=${'chip chip-maintree-' + (run.maintree.phase || 'queued')} title="This run works in the main checkout">${run.maintree.role === 'queued' ? `Main tree: waiting for #${run.maintree.ahead} (position ${run.maintree.position})` : `Main tree: ${run.maintree.phase}${run.maintree.reason ? ' — ' + run.maintree.reason : ''}`}</span>`}
            ${run.maintree && run.maintree.role === 'holder' && run.maintree.phase !== 'done' && html`<button type="button" class="btn" disabled=${busy === 'maintree'} onClick=${this.releaseMainTree} title="Lets the next main-tree run start on top of this one's branch">Release main tree</button>`}
            ${canStartGrind(run) && html`<button type="button" class="btn btn--primary" disabled=${busy === 'grind'} onClick=${() => this.grind('start')} title="Posts a trigger to the repo's Slack review channel">Start grinding</button>`}
            ${run.grind && ['running', 'idle'].includes(run.grind.state) && html`<button type="button" class="btn" disabled=${busy === 'grind'} onClick=${() => this.grind('pause')}>Pause grind</button>`}
            ${run.grind && run.grind.state === 'paused' && run.gh?.pr?.ci === 'red' && html`<button type="button" class="btn" disabled=${busy === 'grind'} onClick=${() => this.grind('rerun-ci')} title="Reruns the failed jobs of the latest CI run on the PR head">Rerun failed CI</button>`}
            ${run.grind && run.grind.state === 'paused' && html`<button type="button" class="btn" disabled=${busy === 'grind' || run.gh?.pr?.ci === 'red'} title=${run.gh?.pr?.ci === 'red' ? 'CI is red at the head commit: rerun it first, or the grind pauses again' : ''} onClick=${() => this.grind('resume')}>Resume grind</button>`}
            ${cleanable && html`<button type="button" class="btn" onClick=${() => openCleanup(`${owner}/${repo}#${n}`)}>Clean up</button>`}
          </div>
        </div>
        ${s && s.outcome === 'limited' && html`<${LimitBanner} key=${s.id} s=${s} />`}
        ${s && s.resumed_fresh && html`<p class="note">${`Resumed fresh${s.note ? `: ${s.note}` : ''}`}</p>`}
        <${FailingChecks} gh=${run.gh} />
        ${run.errors?.ledger && html`<p class="muted">Ledger could not be read</p>`}
        ${run.grind && run.grind.state === 'paused' && html`<section class="panel grind-needs" aria-label="Grind needs you">
          <h2>Grind needs you</h2>
          ${run.grind.reason && html`<p class="note">${run.grind.reason}</p>`}
          ${run.grind.message && html`<div class="md" dangerouslySetInnerHTML=${{ __html: mdToHtml(run.grind.message) }}></div>`}
          ${pausedOnCi(run) && html`<div class="actions">
            <button type="button" disabled=${busy === 'grind'} onClick=${this.skipCi} title=${SKIP_CI_REPLY}>Skip CI for now</button>
          </div>`}
          <form class="prompt-form" onSubmit=${this.replyGrind}>
            <label for="grind-reply">Your decision</label>
            <textarea id="grind-reply" class="field" rows="2" maxlength="4000" placeholder="e.g. go with option (a)…" value=${replyText} onInput=${(e) => this.setState({ replyText: e.target.value })}></textarea>
            <button type="submit" disabled=${!replyText.trim() || busy === 'grind'}>Reply and resume grind</button>
          </form>
        </section>`}
        <div role="status" class="msg">${msg}</div>
        ${fallback && s && html`<label class="cmd">Command <input readOnly value=${s.resume_command} aria-label="Resume command" ref=${this.selectBox} /></label>`}
        <div class="run-cols">
          <div class="panel stations">
            <h2>Stations</h2>
            <ol class="timeline">
              ${stations.map((st) => html`
                <li class=${`st-${KNOWN.includes(st.status) ? st.status : 'other'}`} aria-current=${st.name === run.currentStation ? 'step' : undefined}>
                  <span class="dot" aria-hidden="true"></span>
                  <span class="name">${st.name}</span>
                  ${st.skipped ? html`<span class="chip other" title="Bypassed: the refined issue body was used as the plan">skipped</span>`
                    : st.status === 'done' ? html`<span class="sr-only">done</span>` : html`<span class=${chip(st.status)}>${st.status}</span>`}
                  ${st.bounces > 0 && html`<span class="muted">${`${st.bounces} ${st.bounces === 1 ? 'bounce' : 'bounces'}`}</span>`}
                </li>`)}
            </ol>
            <div class="stats">
              <div><div class="muted">Cost</div><div class="mono big">${money(t.cost)}</div></div>
              ${t.tokens && html`<div><div class="muted">Tokens</div><div class="mono big">${`${t.tokens.input} in / ${t.tokens.output} out`}</div></div>`}
            </div>
            ${stationNote(rt, stations) && html`<p class="muted">${stationNote(rt, stations)}</p>`}
          </div>
          <div class="panel main">
            <div role="tablist" aria-label="Run detail">
              ${TABS.map(([k, label]) => html`
                <button type="button" role="tab" id=${`tab-${k}`} aria-controls="run-panel" aria-selected=${tab === k} onClick=${() => this.setState({ tab: k })}>${label}</button>`)}
            </div>
            <div role="tabpanel" id="run-panel" aria-labelledby=${`tab-${tab}`}>${body}</div>
            ${target && html`<form class="prompt-form composer" onSubmit=${this.sendPrompt}>
              <label for="run-prompt">Send a prompt to the ${sessionLabel(target.command)} session <span class="mono muted">${String(target.id).slice(-8)}</span></label>
              <textarea id="run-prompt" class="field" onKeyDown=${(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); e.currentTarget.form.requestSubmit(); } }} rows="2" maxlength="4000" placeholder="Tell it what to do next…" value=${promptText} onInput=${(e) => this.setState({ promptText: e.target.value })}></textarea>
              <button type="submit" disabled=${!promptText.trim() || busy === 'prompt' || target.outcome === 'waiting'}>Send</button>
              <p class="note">${target.outcome === 'waiting' ? 'Answer the pending question first.' : ['running', 'starting', 'limited'].includes(target.outcome) ? 'It is running: the prompt is queued and goes out when it ends.' : 'Resumes the session with this prompt.'}</p>
              ${target.queued_prompt && html`<p class="note">Queued: ${target.queued_prompt}</p>`}
            </form>`}
          </div>
        </div>
      </section>
    `;
  }
}
