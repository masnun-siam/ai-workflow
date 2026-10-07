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
  'gh-issue': 'Type (bug, feature, task, improvement) and details',
};
const COMMANDS = Object.keys(LABELS);
const OPTIONAL_ARGS = new Set(['worklog']);
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
  state = { repos: [], repo: '', manual: false, path: '', command: 'run-issue', args: '', text: '', pending: false, errors: {}, result: null, form: 'named', repoQuery: null, repoOpen: false, repoActive: 0 };

  async componentDidMount() {
    fetch('/api/settings', { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => s && this.setState({ cmds: s.commands || [], claudeLabel: s.default || '' }))
      .catch(() => {}); // no picker without settings: runs use claude
    let repos = [];
    let failed = false;
    try {
      const res = await fetch('/api/repos', { headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      repos = repoOptions(await res.json());
    } catch {
      failed = true;
    }
    const last = loadLastRepo(globalThis.localStorage);
    const known = repos.find((r) => r.value === last);
    this.setState({
      repos,
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
    const r = await this.submit({ ...mkBody(repo), ...(s.claudeLabel ? { claude_cmd: s.claudeLabel } : {}) });
    if (!r) return;
    this.setState({ pending: false, result: r.kind === 'open' ? null : r });
    if (r.kind === 'open') {
      saveLastRepo(globalThis.localStorage, repo);
      toast('Session started');
      location.hash = r.href;
    }
  };

  // Repo combobox: one input that filters repos as you type, and also takes an absolute path.
  pickRepo = (opt) => {
    if (opt.kind === 'repo') this.setState({ repo: opt.value, manual: false, repoQuery: null, repoOpen: false });
    else if (opt.kind === 'path') this.setState({ manual: true, path: opt.path, repoQuery: null, repoOpen: false });
    else this.setState({ manual: true, path: '', repoQuery: '', repoOpen: false });
  };

  onComboInput = (e) => {
    const q = e.target.value;
    const path = pathOption(q);
    this.setState({ repoQuery: q, repoOpen: true, repoActive: 0, ...(path ? { manual: true, path } : {}) });
  };

  onComboKey = (e) => {
    const opts = comboOptions(this.state.repos, this.state.repoQuery);
    const n = opts.length;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const step = e.key === 'ArrowDown' ? 1 : n - 1;
      this.setState({ repoOpen: true, repoActive: (this.state.repoActive + step) % n });
    } else if (e.key === 'Enter' && this.state.repoOpen && n) {
      e.preventDefault();
      this.pickRepo(opts[Math.min(this.state.repoActive, n - 1)]);
    } else if (e.key === 'Escape' && this.state.repoOpen) {
      e.preventDefault();
      this.setState({ repoOpen: false, repoQuery: null });
    }
  };

  onSubmit = (ev) => this.start(ev, 'named', validate(this.state), (repo) => buildBody({ repo, command: this.state.command, args: this.state.args }));

  onCustom = (ev) => this.start(ev, 'custom', validateCustom(this.state), (repo) => buildCustomBody({ repo, text: this.state.text }));

  render({ limits }, { cmds, claudeLabel, repos, repo, manual, path, command, args, text, pending, form, errors, result, repoQuery, repoOpen, repoActive }) {
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
        ${repos.length
          ? html`<div class="combo">
              <input id="repo-path" type="text" class="combo-input" role="combobox" autocomplete="off" spellcheck="false"
                aria-expanded=${repoOpen ? 'true' : 'false'} aria-controls="repo-list" aria-autocomplete="list"
                aria-activedescendant=${repoOpen ? 'repo-opt-' + repoActive : undefined}
                placeholder="Search repos or type an absolute path"
                value=${repoQuery !== null ? repoQuery : manual ? path : (repos.find((r) => r.value === repo) || {}).label || ''}
                onInput=${this.onComboInput} onKeyDown=${this.onComboKey}
                onFocus=${(e) => { e.target.select(); this.setState({ repoOpen: true }); }}
                onBlur=${() => this.setState({ repoOpen: false, repoQuery: null })}
                aria-invalid=${repoMsg ? 'true' : undefined} aria-describedby=${repoMsg ? 'repo-error' : undefined} />
              ${repoOpen && html`<ul id="repo-list" class="combo-list" role="listbox" aria-label="Repos">
                ${comboOptions(repos, repoQuery).map((o, i) => html`<li id=${'repo-opt-' + i} role="option" key=${i}
                  aria-selected=${i === repoActive ? 'true' : 'false'} class=${o.kind === 'repo' && !manual && o.value === repo ? 'current' : ''}
                  onMouseDown=${(e) => e.preventDefault()} onMouseEnter=${() => this.setState({ repoActive: i })} onClick=${() => this.pickRepo(o)}>
                  ${o.kind === 'repo' ? html`<span>${o.name}</span><small class="mono">${o.path}</small>`
                    : o.kind === 'path' ? html`<span>Use path</span><small class="mono">${o.path}</small>`
                    : html`<span>Other path…</span><small>Type an absolute path to a git checkout</small>`}
                </li>`)}
              </ul>`}
            </div>`
          : html`<input id="repo-path" type="text" value=${path} onInput=${set('path')}
              aria-invalid=${repoMsg ? 'true' : undefined} aria-describedby=${repoMsg ? 'repo-error' : undefined} />`}
        ${repoMsg ? html`<p id="repo-error" role="alert" class="error">${repoMsg}</p>` : null}
        ${cmds && cmds.length > 0 && html`
          <label for="claude-cmd">Claude command</label>
          <select id="claude-cmd" value=${claudeLabel} onChange=${set('claudeLabel')}>
            <option value="" selected=${!claudeLabel}>claude</option>
            ${cmds.map((c) => { const until = ((limits || {})[c.cmd] || {}).limited_until; return html`<option value=${c.label} selected=${c.label === claudeLabel}>${c.label}${until ? ` (limited until ${clockText(until)})` : ''}</option>`; })}
          </select>
          ${(((limits || {})[(cmds.find((c) => c.label === claudeLabel) || {}).cmd] || {}).limited_until) ? html`<p class="note">This account is rate limited: the run is queued and starts automatically at reset.</p>` : null}`}
        <fieldset>
          <legend>Command</legend>
          ${COMMANDS.map((c) => html`<label for=${'cmd-' + c} class="radio">
            <input id=${'cmd-' + c} type="radio" name="command" value=${c} checked=${command === c} onChange=${set('command')} />
            ${c}</label>`)}
        </fieldset>
        <label for="args">${LABELS[command]}</label>
        <input id="args" type="text" value=${args} onInput=${set('args')}
          aria-invalid=${errors.args ? 'true' : undefined} aria-describedby=${errors.args ? 'args-error' : undefined} />
        ${errors.args ? html`<p id="args-error" role="alert" class="error">${errors.args}</p>` : null}
        ${outcomeMsg('named')}
        <div class="launch-actions">
          <button type="submit" disabled=${pending}>${pending && (form || 'named') === 'named' ? 'Starting...' : 'Start'}</button>
          <span class="note">Runs headless in the chosen checkout</span>
        </div>
      </form>
      <aside class="launch-side">
      <form class="launcher panel" onSubmit=${this.onCustom} noValidate>
        <h2>Custom command</h2>
        <label for="custom">Custom command or prompt</label>
        <textarea id="custom" placeholder="/pr-fix-comments 42" value=${text} onInput=${set('text')}
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
