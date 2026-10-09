import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { toast } from './toast.js';
import { clockText } from './fmt.js';

const html = htm.bind(h);
const KEY = 'aiw.lastRepo';
const LABELS = {
  'run-issue': 'Issue number or URL',
  'pr-grind': 'PR number or URL',
  prd: 'Requirement: free text, file path, vault note or issue URL',
  intake: 'Sentry URL, file path, vault note or free text',
  dump: 'What to capture: feature, change, bug or task',
  worklog: 'Date (optional, defaults to today)',
  day: 'What to capture: a task, follow-up or meeting notes (leave empty to plan, shut down or review the week)',
  'gh-issue': 'Type (bug, feature, task, improvement) and details',
  'pr-review': 'PR number or URL to review',
  'pr-fix-comments': 'PR URL or owner/repo#123',
  'issue-to-pr': 'Issue URL',
};
const COMMANDS = Object.keys(LABELS);
const HINTS = {
  'run-issue': '5940, or an issue URL',
  'pr-grind': 'The Slack link of the review thread',
  worklog: '2026-10-08',
  'pr-review': '5960, or a PR URL',
  'pr-fix-comments': 'owner/repo#5960, or a PR URL',
  'issue-to-pr': 'An issue URL',
};
const OPTIONAL_ARGS = new Set(['worklog', 'day']);
// These take a written description rather than a number or link, so they get room to write.
export const FREE_TEXT = new Set(['prd', 'intake', 'dump', 'gh-issue', 'day']);
const URL_KIND = { 'run-issue': 'issues', 'pr-grind': 'pull' };

export function repoOptions(body) {
  const list = body && Array.isArray(body.repos) ? body.repos : [];
  return list
    .filter((r) => r && typeof r.slug === 'string' && typeof r.path === 'string')
    .map((r) => ({ value: r.slug, label: `${r.name || r.slug} - ${r.path}`, name: r.name || r.slug, path: r.path }));
}

// A typed absolute path is usable as-is; the server validates that it is a git checkout.
export function pathOption(query) {
  const q = String(query ?? '').trim();
  return q.startsWith('/') ? q : null;
}

// Options for the repo combobox: repos matching the query, a "use this path" entry for a typed
// absolute path, and a closing "Other path" entry that switches to free entry.
export function comboOptions(repos, query) {
  const q = String(query ?? '').trim().toLowerCase();
  const out = repos
    .filter((r) => !q || r.label.toLowerCase().includes(q) || r.value.toLowerCase().includes(q))
    .map((r) => ({ kind: 'repo', value: r.value, name: r.name, path: r.path }));
  const path = pathOption(query);
  if (path) out.push({ kind: 'path', path });
  out.push({ kind: 'other' });
  return out;
}

// The repo combobox shared by New run and Flow: one input that filters repos as you type, also
// takes an absolute path, plus the native folder picker. It is a render helper, not a component,
// so its state (repo, manual, path, repoQuery, repoOpen, repoActive, browsing) lives on the host
// and the host's own render tree contains the input. onPick runs after a repo or path is chosen.
export function repoCombo(host, onPick = () => {}) {
  const pick = (opt) => {
    const patch = opt.kind === 'repo' ? { repo: opt.value, manual: false }
      : opt.kind === 'path' ? { manual: true, path: opt.path } : { manual: true, path: '' };
    host.setState({ ...patch, repoQuery: opt.kind === 'other' ? '' : null, repoOpen: false }, onPick);
  };
  // Native folder dialog opened by the server on this Mac; the server still validates the git checkout.
  const browse = async () => {
    const s = host.state;
    const start = s.manual ? s.path : (s.repos.find((r) => r.value === s.repo) || {}).path;
    host.setState({ browsing: true });
    try {
      const res = await fetch('/api/repos/browse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ start: start || '' }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const { path } = await res.json();
      if (path) host.setState({ manual: true, path, repoQuery: null, repoOpen: false }, onPick);
    } catch {
      toast('Could not open the folder picker');
    } finally {
      host.setState({ browsing: false });
    }
  };
  const input = (e) => {
    const q = e.target.value;
    const path = pathOption(q);
    host.setState({ repoQuery: q, repoOpen: true, repoActive: 0, ...(path ? { manual: true, path } : {}) }, path ? onPick : undefined);
  };
  const key = (e) => {
    const s = host.state;
    const opts = comboOptions(s.repos, s.repoQuery);
    const n = opts.length;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      host.setState({ repoOpen: true, repoActive: ((s.repoActive || 0) + (e.key === 'ArrowDown' ? 1 : n - 1)) % n });
    } else if (e.key === 'Enter' && s.repoOpen && n) {
      e.preventDefault();
      pick(opts[Math.min(s.repoActive || 0, n - 1)]);
    } else if (e.key === 'Escape' && s.repoOpen) {
      e.preventDefault();
      host.setState({ repoOpen: false, repoQuery: null });
    }
  };
  const render = ({ repos, repo, manual, path, repoQuery, repoOpen, repoActive, canBrowse, browsing }, { id, error }) => {
    const list = `${id}-list`;
    const known = repos.find((r) => r.value === repo) || {};
    return html`<div class="repo-row">
      ${repos.length
      ? html`<div class="combo">
          <input id=${id} type="text" class="combo-input" role="combobox" autocomplete="off" spellcheck="false"
            aria-expanded=${repoOpen ? 'true' : 'false'} aria-controls=${list} aria-autocomplete="list"
            aria-activedescendant=${repoOpen ? `${id}-opt-${repoActive || 0}` : undefined}
            placeholder="Search repos or type an absolute path"
            value=${repoQuery != null ? repoQuery : manual ? path : known.name || repo || ''}
            title=${manual ? path : known.path || ''}
            onInput=${input} onKeyDown=${key}
            onFocus=${(e) => { e.target.select(); host.setState({ repoOpen: true }); }}
            onBlur=${() => host.setState({ repoOpen: false, repoQuery: null })}
            aria-invalid=${error ? 'true' : undefined} aria-describedby=${error || undefined} />
          ${repoOpen && html`<ul id=${list} class="combo-list" role="listbox" aria-label="Repos">
            ${comboOptions(repos, repoQuery).map((o, i) => html`<li id=${`${id}-opt-${i}`} role="option" key=${i}
              aria-selected=${i === (repoActive || 0) ? 'true' : 'false'} class=${o.kind === 'repo' && !manual && o.value === repo ? 'current' : ''}
              onMouseDown=${(e) => e.preventDefault()} onMouseEnter=${() => host.setState({ repoActive: i })} onClick=${() => pick(o)}>
              ${o.kind === 'repo' ? html`<span>${o.name}</span><small class="mono">${o.path}</small>`
                : o.kind === 'path' ? html`<span>Use path</span><small class="mono">${o.path}</small>`
                : html`<span>Other path…</span><small>Type an absolute path to a git checkout</small>`}
            </li>`)}
          </ul>`}
        </div>`
      : html`<input id=${id} type="text" value=${path} onInput=${(e) => host.setState({ path: e.target.value }, onPick)}
          aria-invalid=${error ? 'true' : undefined} aria-describedby=${error || undefined} />`}
      ${canBrowse && html`<button type="button" class="browse-btn" aria-label="Browse for a folder" title="Browse for a folder"
        disabled=${browsing} onClick=${browse}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
      </button>`}
    </div>`;
  };
  return { render, pick };
}

// Reset time (epoch s) of the chosen account when it is rate limited, else null.
export function limitedUntil(cmds, label, limits) {
  const c = (cmds || []).find((x) => x.label === label);
  return (c && ((limits || {})[c.cmd] || {}).limited_until) || null;
}

// Registered repo named by a GitHub URL or owner/repo#N in the text, else null.
export function repoFromText(repos, text) {
  const m = /(?:github\.com\/|(?:^|\s))([\w.-]+\/[\w.-]+)(?:\/(?:issues|pull)\/\d+|#\d+)/.exec(String(text ?? ''));
  const hit = m && repos.find((r) => r.value.toLowerCase() === m[1].toLowerCase());
  return hit ? hit.value : null;
}

export function argIssue(command, args) {
  const s = String(args ?? '').trim();
  const m = /^#?(\d+)$/.exec(s) || new RegExp(`^https?://[^/\\s]+/[^/\\s]+/[^/\\s]+/${URL_KIND[command]}/(\\d+)/?$`).exec(s);
  const n = m ? Number(m[1]) : 0;
  return n > 0 ? n : null;
}

export function validate({ repo, path, manual, command, args }) {
  const errors = {};
  if (!String((manual ? path : repo) ?? '').trim()) errors.repo = 'Choose a repo or enter a path';
  if (!OPTIONAL_ARGS.has(command) && !String(args ?? '').trim()) errors.args = `Enter ${LABELS[command].toLowerCase()}`;
  return Object.keys(errors).length ? errors : null;
}

export function validateCustom({ repo, path, manual, text }) {
  const errors = {};
  if (!String((manual ? path : repo) ?? '').trim()) errors.repo = 'Choose a repo or enter a path';
  if (!String(text ?? '').trim()) errors.text = 'Enter a command or prompt';
  return Object.keys(errors).length ? errors : null;
}

export function buildCustomBody({ repo, text }) {
  return { repo, text: String(text).trim() };
}

export function buildBody({ repo, command, args }) {
  const a = String(args).trim();
  const body = { repo, command, args: a };
  const issue = command === 'pr-grind' ? argIssue(command, a) : null;
  if (issue) body.issue = issue;
  return body;
}

export function sessionHref(body, command) {
  // pr-grind has no per-session route yet (#126); #/run/ is the issue-keyed ledger
  if (command === 'pr-grind') return '#/sessions';
  const l = body && body.link;
  if (!l || !l.owner || !l.repo || !Number.isInteger(l.issue) || l.issue < 1) return '#/sessions';
  return `#/run/${encodeURIComponent(l.owner)}/${encodeURIComponent(l.repo)}/${l.issue}`;
}

export function outcome(status, body, command) {
  const err = body && typeof body.error === 'string' ? body.error : `Request failed (HTTP ${status})`;
  if (status === 201) return { kind: 'open', href: sessionHref(body, command) };
  if (status === 409) return { kind: 'duplicate', message: err, href: sessionHref(body, command) };
  if (status === 400 && err.startsWith('not a git repository')) return { kind: 'repo', message: err };
  return { kind: 'error', message: err };
}

export function loadLastRepo(storage) {
  try {
    return storage.getItem(KEY) || null;
  } catch {
    return null;
  }
}

export function saveLastRepo(storage, value) {
  try {
    storage.setItem(KEY, value);
  } catch {
    // storage unavailable: remembering the repo is best-effort
  }
}

export function makeSubmitter(fetchImpl) {
  let inflight = false;
  return async function submit(body) {
    if (inflight) return null;
    inflight = true;
    try {
      const res = await fetchImpl('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      let data = null;
      try {
        data = await res.json();
      } catch {
        // non-JSON body: outcome falls back to the HTTP status
      }
      return outcome(res.status, data, body.command);
    } catch {
      return { kind: 'error', message: 'could not reach the aiw server' };
    } finally {
      inflight = false;
    }
  };
}

export class Launcher extends Component {
  state = { repos: [], repo: '', manual: false, path: '', command: 'run-issue', args: '', text: '', pending: false, errors: {}, result: null, form: 'named', repoQuery: null, repoOpen: false, repoActive: 0, canBrowse: false, browsing: false };

  async componentDidMount() {
    fetch('/api/settings', { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => s && this.setState({ cmds: s.commands || [], claudeLabel: s.default || '', autoGrind: !!s.auto_grind }))
      .catch(() => {}); // no picker without settings: runs use claude
    let repos = [];
    let failed = false;
    let canBrowse = false;
    try {
      const res = await fetch('/api/repos', { headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      repos = repoOptions(body);
      canBrowse = body.can_browse === true;
    } catch {
      failed = true;
    }
    const last = loadLastRepo(globalThis.localStorage);
    const known = repos.find((r) => r.value === last);
    this.setState({
      repos,
      canBrowse,
      repo: known ? known.value : repos.length ? repos[0].value : '',
      manual: !known && !!last && last.startsWith('/') ? true : repos.length === 0,
      path: !known && last && last.startsWith('/') ? last : '',
      result: failed ? { kind: 'error', message: 'could not load repos' } : null,
    });
  }

  start = async (ev, form, errors, mkBody) => {
    ev.preventDefault();
    const s = this.state;
    if (errors) {
      this.setState({ errors, result: null });
      return;
    }
    this.submit = this.submit || makeSubmitter((...a) => fetch(...a));
    const repo = (s.manual || !s.repos.length ? s.path : s.repo).trim();
    this.setState({ pending: true, form, errors: {}, result: null });
    const r = await this.submit({ ...mkBody(repo), ...(s.claudeLabel ? { claude_cmd: s.claudeLabel } : {}), auto_grind: s.autoGrind === true });
    if (!r) return;
    this.setState({ pending: false, result: r.kind === 'open' ? null : r });
    if (r.kind === 'open') {
      saveLastRepo(globalThis.localStorage, repo);
      toast('Session started');
      location.hash = r.href;
    }
  };

  combo = repoCombo(this, () => this.setState({ errors: { ...this.state.errors, repo: undefined }, result: null }));

  // Typing an issue/PR link picks its repo from the dropdown when it is registered.
  setText = (k) => (e) => {
    const v = e.target.value;
    const hit = repoFromText(this.state.repos, v);
    this.setState({ [k]: v, ...(hit ? { repo: hit, manual: false, repoQuery: null } : {}) });
  };

  onSubmit = (ev) => this.start(ev, 'named', validate(this.state), (repo) => buildBody({ repo, command: this.state.command, args: this.state.args }));

  onCustom = (ev) => this.start(ev, 'custom', validateCustom(this.state), (repo) => buildCustomBody({ repo, text: this.state.text }));

  render({ limits }, { canBrowse, browsing, cmds, claudeLabel, autoGrind, repos, repo, manual, path, command, args, text, pending, form, errors, result, repoQuery, repoOpen, repoActive }) {
    const set = (k) => (e) => this.setState({ [k]: e.target.value });
    const mine = (f) => (result && (form || 'named') === f ? result : null);
    const outcomeMsg = (f) => { const r = mine(f); return r && r.kind === 'duplicate'
      ? html`<p role="alert" class="error">${r.message} <a href=${r.href}>Open that run</a></p>`
      : r && r.kind === 'error' ? html`<p role="alert" class="error">${r.message}</p>` : null; };
    const repoMsg = errors.repo || (result && result.kind === 'repo' ? result.message : null);
    return html`
      <div class="launch">
      <form class="launcher panel" onSubmit=${this.onSubmit} noValidate>
        <h1>New run</h1>
        <label for="repo-path">${repos.length ? 'Repo' : 'Repo path'}</label>
        ${this.combo.render({ repos, repo, manual, path, repoQuery, repoOpen, repoActive, canBrowse, browsing }, { id: 'repo-path', error: repoMsg ? 'repo-error' : null })}
        ${repoMsg ? html`<p id="repo-error" role="alert" class="error">${repoMsg}</p>` : null}
        <fieldset>
          <legend>Command</legend>
          ${COMMANDS.map((c) => html`<label for=${'cmd-' + c} class="radio">
            <input id=${'cmd-' + c} type="radio" name="command" value=${c} checked=${command === c} onChange=${set('command')} />
            ${c}</label>`)}
        </fieldset>
        <label for="args">${LABELS[command]}</label>
        ${FREE_TEXT.has(command)
          ? html`<textarea id="args" class="args-text" rows="8" value=${args} onInput=${this.setText('args')}
              onKeyDown=${(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); e.target.form.requestSubmit(); } }}
              aria-invalid=${errors.args ? 'true' : undefined} aria-describedby=${errors.args ? 'args-error' : undefined}></textarea>`
          : html`<input id="args" type="text" placeholder=${HINTS[command] || ''} value=${args} onInput=${this.setText('args')}
              aria-invalid=${errors.args ? 'true' : undefined} aria-describedby=${errors.args ? 'args-error' : undefined} />`}
        ${errors.args ? html`<p id="args-error" role="alert" class="error">${errors.args}</p>` : null}
        ${limitedUntil(cmds, claudeLabel, limits) ? html`<p class="note">This account is rate limited: the run is queued and starts automatically at reset.</p>` : null}
        ${command === 'run-issue' && html`<label class="check" for="auto-grind"><input id="auto-grind" type="checkbox" checked=${autoGrind === true} onChange=${(e) => this.setState({ autoGrind: e.target.checked })} /> Start review grinding when the run finishes</label>`}
        ${outcomeMsg('named')}
        <div class="launch-actions">
          <button type="submit" disabled=${pending}>${pending && (form || 'named') === 'named' ? 'Starting...' : 'Start'}${FREE_TEXT.has(command) && html` <kbd>⌘↵</kbd>`}</button>
          ${cmds && cmds.length > 1 && html`<div class="runas" role="radiogroup" aria-label="Run as">
            <span class="runas-label" aria-hidden="true">Run as</span>
            <div class="seg">
              ${cmds.map((o) => {
                const until = limitedUntil(cmds, o.label, limits);
                return html`<button type="button" role="radio" aria-checked=${claudeLabel === o.label} class=${claudeLabel === o.label ? 'on' : ''}
                  title=${until ? `Limited until ${clockText(until)}` : ''} onClick=${() => this.setState({ claudeLabel: o.label })}>
                  ${until && html`<span class="runas-limited" aria-label="rate limited"></span>`}${o.label}</button>`;
              })}
            </div>
          </div>`}
        </div>
      </form>
      <aside class="launch-side">
      <form class="launcher panel" onSubmit=${this.onCustom} noValidate>
        <h2>Custom command</h2>
        <label for="custom">Custom command or prompt</label>
        <textarea id="custom" placeholder="/pr-fix-comments 42" value=${text} onInput=${this.setText('text')}
          aria-invalid=${errors.text ? 'true' : undefined} aria-describedby=${errors.text ? 'custom-error' : undefined}></textarea>
        ${errors.text ? html`<p id="custom-error" role="alert" class="error">${errors.text}</p>` : null}
        <p class="note danger">Runs with --dangerously-skip-permissions: the command or prompt is not gated.</p>
        ${outcomeMsg('custom')}
        <button type="submit" disabled=${pending}>${pending && form === 'custom' ? 'Starting...' : 'Run in selected repo'}</button>
      </form>
      </aside>
      </div>
    `;
  }
}
