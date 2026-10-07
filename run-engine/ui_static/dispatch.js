import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { poll } from './app.js';
import { toast } from './toast.js';
import { GhChips } from './ghstatus.js';
import { formatWhen } from './fmt.js';

const html = htm.bind(h);

export const STATE_LABEL = {
  queued: 'Queued', running: 'Running', waiting: 'Waiting on you', limited: 'Limited',
  done: 'Done', failed: 'Failed', stopped: 'Stopped', skipped: 'Skipped',
};
const STATIONS = ['researcher', 'planner', 'sdet', 'dev', 'verifier', 'reviewer', 'fixer', 'done'];
const STATION_LABEL = { researcher: 'Research', planner: 'Plan', sdet: 'SDET', dev: 'Dev', verifier: 'Verify', reviewer: 'Review', fixer: 'Fix', done: 'Done' };
const LIVE = ['running', 'waiting', 'limited'];

// ---- pure helpers (unit-tested in test_ui_static.py) -------------------------------------------

// The repo picker is only needed when the pasted text names no repo itself.
export const hasUrl = (text) => /github\.com\//i.test(String(text || ''));

// Issues that screen ready start ticked; flagged ones (gaps, open PR, running, closed) start unticked.
export const defaultSelection = (items) => new Set((items || []).filter((i) => i.ready).map((i) => i.issue));

export function startBody(preview, selected, { mode, max, claude }) {
  const issues = preview.items.map((i) => i.issue).filter((n) => selected.has(n));
  const body = { slug: preview.slug, repo: preview.repo_path, issues, mode, max };
  if (claude) body.claude_cmd = claude;
  return body;
}

export function itemActions(item) {
  if (item.state === 'failed' || item.state === 'stopped') return ['retry', 'skip'];
  if (item.state === 'skipped') return item.reason === 'manual' ? ['retry'] : [];
  if (item.state === 'queued') return ['skip'];
  return [];
}

export function pipelineActions(status) {
  return { active: ['pause', 'stop'], paused: ['resume', 'stop'], stopped: ['resume'], done: [] }[status] || [];
}

export function counts(items) {
  const out = {};
  for (const i of items || []) out[i.state] = (out[i.state] || 0) + 1;
  return out;
}

// "3 of 6 done · 2 running · 1 failed"
export function progressText(items) {
  const c = counts(items);
  const bits = [`${c.done || 0} of ${(items || []).length} done`];
  for (const k of ['running', 'waiting', 'limited', 'failed', 'stopped', 'skipped']) if (c[k]) bits.push(`${c[k]} ${k}`);
  return bits.join(' · ');
}

// Issue numbers out of free text: "#12, 14" or a list of issue URLs.
export function issueNumbers(text) {
  const s = String(text || '');
  const found = s.includes('/') ? [...s.matchAll(/issues\/(\d+)/g)].map((m) => m[1]) : s.match(/\d+/g) || [];
  return [...new Set(found.map(Number).filter((n) => n > 0))];
}

export const statusLabel = (p) => (p.status === 'done' ? 'Finished' : p.status === 'paused' ? 'Paused' : p.status === 'stopped' ? 'Stopped' : 'Running');

async function api(path, body) {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body || {}),
    });
    let data = null;
    try { data = await res.json(); } catch { /* non-JSON error body */ }
    return res.ok ? { ok: true, data } : { ok: false, error: (data && data.error) || `Request failed (HTTP ${res.status})` };
  } catch {
    return { ok: false, error: 'could not reach the aiw server' };
  }
}

// ---- shared pieces -----------------------------------------------------------------------------

// One segment per issue, coloured by state. In the detail view a segment jumps to its row.
function Bar({ issues, onPick }) {
  return html`<div class="bar" role="img" aria-label=${progressText(issues)}>
    ${issues.map((i) => onPick
      ? html`<button type="button" class=${`seg-i s-${i.state}`} title=${`#${i.issue} · ${STATE_LABEL[i.state]}`} aria-label=${`#${i.issue} ${STATE_LABEL[i.state]}`} onClick=${() => onPick(i.issue)}></button>`
      : html`<i class=${`seg-i s-${i.state}`} title=${`#${i.issue} · ${STATE_LABEL[i.state]}`}></i>`)}
  </div>`;
}

function Rail({ run, state }) {
  const rows = run && run.stations && run.stations.length ? run.stations : STATIONS.map((name) => ({ name, status: 'pending' }));
  const cur = run && run.currentStation;
  return html`<div class="rail" aria-label="run-issue stations">
    <ol>${rows.map((r) => html`<li class=${`rs rs-${r.status}${r.name === cur && LIVE.includes(state) ? ' rs-now' : ''}`} title=${`${STATION_LABEL[r.name] || r.name} · ${r.status}${r.bounces ? ` · bounced ${r.bounces}×` : ''}`}></li>`)}</ol>
    <span class="rail-label">${cur ? STATION_LABEL[cur] || cur : run && run.status === 'done' ? 'Done' : state === 'queued' ? 'Not started' : ''}</span>
  </div>`;
}

const StatePill = ({ state }) => html`<span class=${`chip dp-${state}`}>${STATE_LABEL[state] || state}</span>`;

// ---- Dispatch: new pipeline + pipeline list -----------------------------------------------------

export class Dispatch extends Component {
  state = { text: '', repos: [], repo: '', cmds: [], claude: '', mode: 'parallel', max: 2, preview: null, selected: new Set(), busy: null, error: null, list: null };

  componentDidMount() {
    fetch('/api/repos', { headers: { Accept: 'application/json' } }).then((r) => (r.ok ? r.json() : null)).then((b) => {
      const repos = ((b && b.repos) || []).filter((r) => r && r.slug);
      const last = (() => { try { return localStorage.getItem('aiw.lastRepo'); } catch { return null; } })();
      this.setState({ repos, repo: (repos.find((r) => r.slug === last) || repos[0] || {}).slug || '' });
    }).catch(() => {});
    fetch('/api/settings', { headers: { Accept: 'application/json' } }).then((r) => (r.ok ? r.json() : null)).then((s) => s && this.setState({ cmds: s.commands || [], claude: s.default || '' })).catch(() => {});
    this.stop = poll('/api/pipelines', 3000, (r) => r.ok && this.setState({ list: r.data.pipelines }));
  }

  componentWillUnmount() { if (this.stop) this.stop(); }

  onText = (e) => this.setState({ text: e.target.value, preview: null, error: null });

  onKey = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); this.runPreview(e.target.value); }
  };

  runPreview = async (typed) => {
    const text = typeof typed === 'string' ? typed : this.state.text;
    const { repo } = this.state;
    if (!text.trim()) { this.setState({ error: 'Paste a GitHub issue search URL or a list of issue numbers' }); return; }
    this.setState({ text, busy: 'preview', error: null, preview: null });
    const r = await api('/api/dispatch/preview', { input: text, repo: hasUrl(text) ? undefined : repo });
    if (!r.ok) { this.setState({ busy: null, error: r.error }); return; }
    this.setState({ busy: null, preview: r.data, selected: defaultSelection(r.data.items) });
  };

  toggle = (n) => {
    const s = new Set(this.state.selected);
    s.has(n) ? s.delete(n) : s.add(n);
    this.setState({ selected: s });
  };

  pick = (which) => {
    const items = this.state.preview.items;
    const keep = which === 'ready' ? items.filter((i) => i.ready) : which === 'all' ? items.filter((i) => !i.problem) : [];
    this.setState({ selected: new Set(keep.map((i) => i.issue)) });
  };

  start = async () => {
    const { preview, selected, mode, max, claude } = this.state;
    this.setState({ busy: 'start', error: null });
    const r = await api('/api/pipelines', startBody(preview, selected, { mode, max, claude }));
    if (!r.ok) { this.setState({ busy: null, error: r.error }); return; }
    toast(`Pipeline started · ${r.data.items.length} issues`);
    location.hash = `#/dispatch/${r.data.id}`;
  };

  render(_, { text, repos, repo, cmds, claude, mode, max, preview, selected, busy, error, list }) {
    const chosen = preview ? preview.items.filter((i) => selected.has(i.issue)).length : 0;
    const flagged = preview ? preview.items.filter((i) => !i.ready).length : 0;
    return html`
      <h1>Dispatch</h1>
      <p class="note dp-lead">Run <code>/run-issue</code> over a batch of issues. Issues that depend on each other run in order.</p>
      <div class="dispatch">
        <section class="panel dp-new" aria-labelledby="dp-new-h">
          <h2 id="dp-new-h">New pipeline</h2>
          <label for="dp-input">Issues</label>
          <textarea id="dp-input" class="field" rows="3" spellcheck="false" value=${text} onInput=${this.onText} onKeyDown=${this.onKey}
            placeholder="https://github.com/owner/repo/issues?q=label%3Aready   or   #12, 14, 15"></textarea>
          <p class="note">A search URL, issue URLs, issue numbers, or a single epic number to run its sub-issues.</p>
          ${!hasUrl(text) && html`<label for="dp-repo">Repo for plain issue numbers</label>
            <select id="dp-repo" value=${repo} onChange=${(e) => this.setState({ repo: e.target.value, preview: null })}>
              ${repos.length ? repos.map((r) => html`<option value=${r.slug}>${r.slug}</option>`) : html`<option value="">No repos yet — start a run once to register one</option>`}
            </select>`}
          <div class="dp-row">
            <button type="button" class="primary" disabled=${busy === 'preview'} onClick=${() => this.runPreview()}>${busy === 'preview' ? 'Reading issues…' : 'Preview issues'} <kbd>⌘↵</kbd></button>
          </div>
          ${error && html`<p role="alert" class="error">${error}</p>`}

          ${preview && html`
            <div class="dp-preview">
              <div class="dp-head">
                <strong>${preview.slug}</strong>
                <span class="muted">${preview.items.length} issue${preview.items.length === 1 ? '' : 's'}${flagged ? ` · ${flagged} need a look` : ''}</span>
                <span class="spacer"></span>
                <button type="button" class="btn-sm" onClick=${() => this.pick('ready')}>Ready only</button>
                <button type="button" class="btn-sm" onClick=${() => this.pick('all')}>All</button>
                <button type="button" class="btn-sm" onClick=${() => this.pick('none')}>None</button>
              </div>
              <ul class="dp-issues">
                ${preview.items.map((i) => html`<li class=${`dp-issue${selected.has(i.issue) ? ' on' : ''}${i.problem ? ' bad' : ''}`}>
                  <label>
                    <input type="checkbox" checked=${selected.has(i.issue)} disabled=${!!i.problem} onChange=${() => this.toggle(i.issue)} />
                    <span class="dp-num mono">#${i.issue}</span>
                    <span class="dp-title">${i.title || 'Untitled'}</span>
                  </label>
                  <div class="dp-flags">
                    ${i.problem && html`<span class="chip dp-failed">${i.problem}</span>`}
                    ${i.skip && html`<span class="chip dp-skipped">${i.skip}</span>`}
                    ${i.gaps && i.gaps.length > 0 && html`<span class="chip dp-waiting" title=${i.gaps.join('; ')}>Missing: ${i.gaps.slice(0, 2).join(', ')}${i.gaps.length > 2 ? ` +${i.gaps.length - 2}` : ''}</span>`}
                    ${i.lane === 'lean' && html`<span class="chip dp-queued">lean</span>`}
                    ${(i.deps || []).map((d) => html`<span class="chip dp-queued" title="runs after this issue">after #${d}${selected.has(d) ? '' : ' (not selected)'}</span>`)}
                    ${(i.ext_deps || []).map((d) => html`<span class="chip dp-queued" title="outside this pipeline, not enforced">needs #${d} (outside)</span>`)}
                  </div>
                </li>`)}
              </ul>
              <div class="dp-opts">
                <div class="seg" role="radiogroup" aria-label="Order">
                  ${['parallel', 'sequential'].map((m) => html`<button type="button" role="radio" aria-checked=${mode === m} class=${mode === m ? 'on' : ''} onClick=${() => this.setState({ mode: m })}>${m === 'parallel' ? 'In parallel' : 'One at a time'}</button>`)}
                </div>
                ${mode === 'parallel' && html`<div class="num" role="group" aria-label="Max at once">
                  <button type="button" aria-label="Fewer" disabled=${max <= 1} onClick=${() => this.setState({ max: max - 1 })}>−</button>
                  <span><b>${max}</b> at once</span>
                  <button type="button" aria-label="More" disabled=${max >= 6} onClick=${() => this.setState({ max: max + 1 })}>+</button>
                </div>`}
                ${cmds.length > 1 && html`<select aria-label="Claude account" value=${claude} onChange=${(e) => this.setState({ claude: e.target.value })}>
                  ${cmds.map((c) => html`<option value=${c.label}>${c.label}</option>`)}
                </select>`}
              </div>
              <p class="note">${mode === 'parallel' ? `Each run brings up its own Docker stack, so ${max} at once is the cap.` : 'Issues run one after another, oldest dependency first.'}</p>
              <button type="button" class="primary dp-go" disabled=${!chosen || busy === 'start'} onClick=${this.start}>${busy === 'start' ? 'Starting…' : chosen ? `Start ${chosen} issue${chosen === 1 ? '' : 's'}` : 'Select issues to start'}</button>
            </div>`}
        </section>

        <section class="dp-list" aria-labelledby="dp-list-h">
          <h2 id="dp-list-h">Pipelines</h2>
          ${list === null ? html`<p class="empty">Loading…</p>`
            : list.length === 0 ? html`<div class="panel dp-empty"><p>No pipelines yet.</p><p class="note">Paste a search URL on the left, preview the issues, and start one. You can run several at once.</p></div>`
            : list.map((p) => html`<a class=${`pcard${p.counts.waiting ? ' attn' : ''}`} href=${`#/dispatch/${p.id}`}>
              <div class="pcard-top">
                <strong class="pcard-name">${p.name}</strong>
                <span class=${`chip dp-p-${p.status}`}>${statusLabel(p)}</span>
              </div>
              <${Bar} issues=${p.issues} />
              <div class="pcard-meta"><span>${progressText(p.issues)}</span><span class="muted">${p.mode === 'sequential' ? 'one at a time' : `${p.max} at once`} · ${formatWhen(new Date(p.created * 1000).toISOString())}</span></div>
              ${p.counts.waiting > 0 && html`<div class="pcard-attn">${p.counts.waiting} waiting on you</div>`}
            </a>`)}
        </section>
      </div>`;
  }
}

// ---- PipelineDetail ----------------------------------------------------------------------------

export class PipelineDetail extends Component {
  state = { data: null, gone: false, offline: false, confirm: null, busy: false, adding: false, addText: '' };

  componentDidMount() {
    this.stop = poll(`/api/pipelines/${encodeURIComponent(this.props.id)}`, 3000, (r) => {
      if (r.ok) this.setState({ data: r.data, offline: false, gone: false });
      else if (r.status === 404) this.setState({ gone: true });
      else this.setState({ offline: true });
    });
  }

  componentWillUnmount() { this.gone = true; clearTimeout(this.confirmTimer); if (this.stop) this.stop(); }

  act = async (path, body, okMsg) => {
    this.setState({ busy: true, confirm: null });
    const r = await api(`/api/pipelines/${encodeURIComponent(this.props.id)}${path}`, body);
    this.setState({ busy: false });
    if (!r.ok) { toast(r.error, 'error'); return false; }
    if (okMsg) toast(okMsg);
    this.refresh();
    return true;
  };

  async refresh() {
    try {
      const res = await fetch(`/api/pipelines/${encodeURIComponent(this.props.id)}`, { headers: { Accept: 'application/json' } });
      if (res.ok && !this.gone) this.setState({ data: await res.json() });
    } catch { /* the poll catches up */ }
  }

  // Destructive buttons ask once: first click arms, second confirms, arming expires.
  arm = (key, fn) => {
    if (this.state.confirm !== key) {
      clearTimeout(this.confirmTimer);
      this.setState({ confirm: key });
      this.confirmTimer = setTimeout(() => this.setState({ confirm: null }), 4000);
    } else fn();
  };

  jump = (n) => {
    const el = document.getElementById(`it-${n}`);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.remove('flash');
    void el.offsetWidth;
    el.classList.add('flash');
  };

  remove = async () => {
    if (await this.act('/delete', {}, 'Pipeline deleted')) location.hash = '#/dispatch';
  };

  addIssues = async (e) => {
    e.preventDefault();
    const add = issueNumbers(this.state.addText);
    if (!add.length) { toast('Enter issue numbers to add', 'error'); return; }
    if (await this.act('/update', { add }, `Added ${add.length} issue${add.length === 1 ? '' : 's'}`)) this.setState({ adding: false, addText: '' });
  };

  render({ id }, { data, gone, offline, confirm, busy, adding, addText }) {
    if (gone) return html`<h1>Pipeline not found</h1><p><a href="#/dispatch">Back to Dispatch</a></p>`;
    if (!data) return html`<p class="empty">${offline ? 'Offline: retrying' : 'Loading…'}</p>`;
    const items = data.items;
    const acts = pipelineActions(data.status);
    const live = items.some((i) => LIVE.includes(i.state));
    return html`
      <div class="pd">
        <p class="crumb"><a href="#/dispatch">Dispatch</a> / ${data.slug}</p>
        <header class="pd-head">
          <h1>${data.name}</h1>
          <span class=${`chip dp-p-${data.status}`}>${statusLabel(data)}</span>
          <span class="spacer"></span>
          ${acts.includes('pause') && html`<button type="button" disabled=${busy} onClick=${() => this.act('/pause', {}, 'Paused: running issues continue, nothing new starts')}>Pause</button>`}
          ${acts.includes('resume') && html`<button type="button" class="primary" disabled=${busy} onClick=${() => this.act('/resume', {}, 'Resumed')}>${data.status === 'stopped' ? 'Resume stopped issues' : 'Resume'}</button>`}
          ${acts.includes('stop') && html`<button type="button" class=${confirm === 'stop' ? 'btn--danger armed' : 'btn--danger'} disabled=${busy} onClick=${() => this.arm('stop', () => this.act('/stop', {}, 'Pipeline stopped'))}>${confirm === 'stop' ? `Stop ${items.filter((i) => LIVE.includes(i.state)).length} running?` : 'Stop'}</button>`}
          <button type="button" class=${confirm === 'del' ? 'btn--danger armed' : ''} disabled=${busy || live} title=${live ? 'Stop the pipeline first' : 'Removes the pipeline only; runs and sessions stay'} onClick=${() => this.arm('del', this.remove)}>${confirm === 'del' ? 'Delete for good?' : 'Delete'}</button>
        </header>

        <section class="panel pd-sum">
          <${Bar} issues=${items} onPick=${this.jump} />
          <div class="pd-sum-row">
            <span>${progressText(items)}</span>
            <span class="spacer"></span>
            <div class="seg" role="radiogroup" aria-label="Order">
              ${['parallel', 'sequential'].map((m) => html`<button type="button" role="radio" aria-checked=${data.mode === m} class=${data.mode === m ? 'on' : ''} disabled=${busy} onClick=${() => data.mode !== m && this.act('/update', { mode: m })}>${m === 'parallel' ? 'In parallel' : 'One at a time'}</button>`)}
            </div>
            ${data.mode === 'parallel' && html`<div class="num" role="group" aria-label="Max at once">
              <button type="button" aria-label="Fewer" disabled=${busy || data.max <= 1} onClick=${() => this.act('/update', { max: data.max - 1 })}>−</button>
              <span><b>${data.max}</b> at once</span>
              <button type="button" aria-label="More" disabled=${busy || data.max >= 6} onClick=${() => this.act('/update', { max: data.max + 1 })}>+</button>
            </div>`}
            <button type="button" onClick=${() => this.setState({ adding: !adding })} aria-expanded=${adding}>Add issues</button>
          </div>
          ${adding && html`<form class="pd-add" onSubmit=${this.addIssues}>
            <input type="text" class="field" autofocus placeholder="#21, 22 or issue URLs" value=${addText} onInput=${(e) => this.setState({ addText: e.target.value })} aria-label="Issues to add" />
            <button type="submit" class="primary" disabled=${busy}>Add</button>
          </form>`}
        </section>

        <ul class="pd-items">
          ${items.map((it) => {
            const run = it.run;
            const sess = it.session;
            const runHref = `#/run/${encodeURIComponent(data.slug.split('/')[0])}/${encodeURIComponent(data.slug.split('/')[1])}/${it.issue}`;
            const ia = itemActions(it);
            return html`<li id=${`it-${it.issue}`} class=${`pd-item s-${it.state}`}>
              <div class="pd-main">
                <div class="pd-title">
                  <a class="mono" href=${runHref}>#${it.issue}</a>
                  <span>${it.title || 'Untitled'}</span>
                </div>
                <div class="pd-sub">
                  ${(it.deps || []).map((d) => html`<a class="chip dp-queued" href=${`#it-${d}`} onClick=${(e) => { e.preventDefault(); this.jump(d); }}>after #${d}</a>`)}
                  ${it.reason && html`<span class="muted">${it.reason}</span>`}
                  ${sess && sess.status === 'limited' && html`<span class="muted">${sess.auto_resume ? 'resumes automatically' : 'usage limit'}</span>`}
                  ${sess && sess.error && html`<span class="error">${sess.error}</span>`}
                </div>
              </div>
              <${Rail} run=${run} state=${it.state} />
              <div class="pd-gh">${run && it.gh && html`<${GhChips} gh=${it.gh} />`}${run && run.pr && html`<a class="chip" href=${run.pr} target="_blank" rel="noopener noreferrer">PR ↗</a>`}</div>
              <div class="pd-state"><${StatePill} state=${it.state} /></div>
              <div class="pd-acts">
                ${it.state === 'waiting' && sess && html`<a class="btn btn-sm btn--primary" href=${`#/answer/${encodeURIComponent(sess.id)}`}>Answer</a>`}
                ${sess && html`<a class="btn btn-sm" href=${`#/session/${encodeURIComponent(sess.id)}`}>Session</a>`}
                ${ia.includes('retry') && html`<button type="button" class="btn-sm" disabled=${busy} onClick=${() => this.act(`/items/${it.issue}/retry`, {}, `Retrying #${it.issue}`)}>Retry</button>`}
                ${ia.includes('skip') && html`<button type="button" class="btn-sm" disabled=${busy} onClick=${() => this.act(`/items/${it.issue}/skip`, {}, `Skipped #${it.issue}`)}>Skip</button>`}
              </div>
            </li>`;
          })}
        </ul>

        ${data.merge_order.length > 0 && html`<section class="panel pd-merge">
          <h2>Merge order</h2>
          <p class="note">PRs are stacked on their dependencies, so merge them in this order.</p>
          <ol>${data.merge_order.map((n) => { const it = items.find((i) => i.issue === n); return html`<li><a href=${it.run.pr} target="_blank" rel="noopener noreferrer">#${n} ${it.title || ''}</a></li>`; })}</ol>
        </section>`}
      </div>`;
  }
}
