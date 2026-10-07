import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';

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
    .map((r) => ({ value: r.slug, label: `${r.name || r.slug} - ${r.path}` }));
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
  state = { repos: [], repo: '', manual: false, path: '', command: 'run-issue', args: '', text: '', pending: false, errors: {}, result: null, form: 'named' };

  async componentDidMount() {
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
    const r = await this.submit(mkBody(repo));
    if (!r) return;
    this.setState({ pending: false, result: r.kind === 'open' ? null : r });
    if (r.kind === 'open') {
      saveLastRepo(globalThis.localStorage, repo);
      location.hash = r.href;
    }
  };

  onSubmit = (ev) => this.start(ev, 'named', validate(this.state), (repo) => buildBody({ repo, command: this.state.command, args: this.state.args }));

  onCustom = (ev) => this.start(ev, 'custom', validateCustom(this.state), (repo) => buildCustomBody({ repo, text: this.state.text }));

  render(_, { repos, repo, manual, path, command, args, text, pending, form, errors, result }) {
    const showPath = manual || repos.length === 0;
    const set = (k) => (e) => this.setState({ [k]: e.target.value });
    const onRepo = (e) => (e.target.value === '' ? this.setState({ manual: true }) : this.setState({ manual: false, repo: e.target.value }));
    const mine = (f) => (result && (form || 'named') === f ? result : null);
    const outcomeMsg = (f) => { const r = mine(f); return r && r.kind === 'duplicate'
      ? html`<p role="alert" class="error">${r.message} <a href=${r.href}>Open that run</a></p>`
      : r && r.kind === 'error' ? html`<p role="alert" class="error">${r.message}</p>` : null; };
    const repoMsg = errors.repo || (result && result.kind === 'repo' ? result.message : null);
    return html`
      <form class="launcher" onSubmit=${this.onSubmit} noValidate>
        <h1>New run</h1>
        ${repos.length
          ? html`<label for="repo-select">Repo</label>
            <select id="repo-select" value=${showPath ? '' : repo} onChange=${onRepo}
              aria-invalid=${repoMsg && !showPath ? 'true' : undefined} aria-describedby=${repoMsg && !showPath ? 'repo-error' : undefined}>
              ${repos.map((r) => html`<option value=${r.value}>${r.label}</option>`)}
              <option value="">Other path...</option>
            </select>`
          : null}
        ${showPath
          ? html`<label for="repo-path">Repo path</label>
            <input id="repo-path" type="text" value=${path} onInput=${set('path')}
              aria-invalid=${repoMsg ? 'true' : undefined} aria-describedby=${repoMsg ? 'repo-error' : undefined} />`
          : null}
        ${repoMsg ? html`<p id="repo-error" role="alert" class="error">${repoMsg}</p>` : null}
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
        <button type="submit" disabled=${pending}>${pending && (form || 'named') === 'named' ? 'Starting...' : 'Start'}</button>
      </form>
      <form class="launcher" onSubmit=${this.onCustom} noValidate>
        <label for="custom">Custom command or prompt</label>
        <textarea id="custom" placeholder="/pr-fix-comments 42" value=${text} onInput=${set('text')}
          aria-invalid=${errors.text ? 'true' : undefined} aria-describedby=${errors.text ? 'custom-error' : undefined}></textarea>
        ${errors.text ? html`<p id="custom-error" role="alert" class="error">${errors.text}</p>` : null}
        <p class="note">Runs with --dangerously-skip-permissions: the command or prompt is not gated.</p>
        ${outcomeMsg('custom')}
        <button type="submit" disabled=${pending}>${pending && form === 'custom' ? 'Starting...' : 'Run in selected repo'}</button>
      </form>
    `;
  }
}
