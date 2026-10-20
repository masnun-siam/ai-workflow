import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { toast } from './toast.js';
import { clockText, loadPref, savePref } from './fmt.js';
import { RepoPicker } from './repopicker.js';
import { CreateRepoDialog, FolderChooser, NO_REPO_COMMANDS, folderOf } from './vault.js';

const html = htm.bind(h);
const KEY = 'aiw.lastRepo';
const LABELS = {
  'implement-issue': 'Issue number or URL',
  'pr-grind': 'PR number or URL',
  'create-prd': 'Requirement: free text, file path, vault note or issue URL',
  dump: 'What to capture: feature, change, bug or task',
  worklog: 'Date (optional, defaults to today)',
  day: 'What to capture: a task, follow-up or meeting notes (leave empty to plan, shut down or review the week)',
  'refine-issues': 'Epic number or issue numbers',
  'pr-review': 'PR number or URL to review',
  'verifier-locally': 'What to verify (optional, defaults to the current change)',
  'docs-updater': 'Focus (optional, defaults to what changed since the last docs update)',
  'sync-from-wasensi': 'Focus (optional, defaults to everything that changed upstream)',
  'skill-feedback': 'Feedback on a skill or guide, or reconcile to mine the learning logs of closed PRs',
  'create-tasks': 'PRD file path, or a finding to file as one issue',
  'herdr-dispatch': 'Epic number, issue numbers, a label or an issue-search URL',
  flow: 'An idea, a PRD path or an epic number',
  'peer-review': 'What to review (optional, defaults to this session\'s change)',
  'release-pr': 'Options (optional): --dry-run, or what to hold back',
};
const COMMANDS = Object.keys(LABELS);
// What each command does, grouped by the job it serves, so nobody has to know the slugs by heart.
export const GROUPS = [
  ['Build', [['implement-issue', 'Issue to a verified, reviewed ready PR'], ['herdr-dispatch', 'Run several issues in herdr tabs'], ['verifier-locally', 'Run the checks that match the change']]],
  ['Review', [['pr-review', 'Review a PR or branch, with a verdict'], ['pr-grind', 'Loop the Slack reviewer bot on a ready PR'], ['peer-review', 'Panel of lens reviewers on an artifact']]],
  ['Plan', [['flow', 'Idea to running issues, stage by stage'], ['create-prd', 'Idea to a PRD with technical design'], ['create-tasks', 'PRD to tasks and child issues of its epic'], ['refine-issues', 'Write WHAT, WHY and HOW into issues']]],
  ['Ship', [['release-pr', 'Staging to master release PR, then grind']]],
  ['Capture', [['dump', 'File an idea into your notes vault'], ['day', 'Tasks and follow-ups into Todoist'], ['worklog', "A day's worklog from GitHub activity"]]],
  ['Maintain', [['docs-updater', 'Bring docs/ in line with the code'], ['sync-from-wasensi', 'Port upstream skill changes into the plugin'], ['skill-feedback', 'Turn feedback into skill and guide edits']]],
];
// Worklog's day: today, yesterday, one picked day, or a range. The skill writes one daily note per
// day, so a range starts one worklog run per day. Dates are local YYYY-MM-DD.
export const WORKLOG_MAX_DAYS = 31;
export const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const dayAfter = (iso) => { const [y, m, d] = iso.split('-').map(Number); return isoDay(new Date(y, m - 1, d + 1)); };

// { dates } to run, or { error }. `today` is the local date, passed in for tests.
export function worklogDates({ mode = 'today', day = '', from = '', to = '' }, today) {
  if (mode === 'today' || mode === 'yesterday') return { dates: [mode] };
  if (mode === 'day') {
    if (!day) return { error: 'Pick a day' };
    return day > today ? { error: 'Pick a day that has happened' } : { dates: [day] };
  }
  if (!from || !to) return { error: 'Pick both the first and the last day' };
  if (from > to) return { error: 'The first day must come before the last' };
  if (to > today) return { error: 'The last day cannot be in the future' };
  const dates = [];
  for (let d = from; d <= to && dates.length <= WORKLOG_MAX_DAYS; d = dayAfter(d)) dates.push(d);
  return dates.length > WORKLOG_MAX_DAYS ? { error: `Pick at most ${WORKLOG_MAX_DAYS} days` } : { dates };
}

// Commands whose argument is one of the repo's open issues or PRs: New run lists them to pick from.
export const PICK = { 'implement-issue': 'issue', 'pr-review': 'pr' };
const CMD_KEY = 'aiw.lastCommand';

// The argument text a picked issue/PR fills in, in the form each command takes (the URL is gh's).
export function pickValue(command, slug, item) {
  return String(item.number);
}

// The number the typed argument names, in any form pickValue writes (or a pasted issue/PR URL).
export function typedNumber(args) {
  const m = /^#?(\d+)$/.exec(String(args ?? '').trim()) || /(?:#|\/(?:issues|pull)\/)(\d+)\/?$/.exec(String(args ?? '').trim());
  return m ? Number(m[1]) : null;
}

// Typing filters the list: a number matches by prefix, words match the title or a label.
export function matchItems(items, args) {
  const q = String(args ?? '').trim().toLowerCase();
  if (!q || typedNumber(q) && !/^#?\d+$/.test(q)) return items || [];
  const num = /^#?(\d+)$/.exec(q);
  return (items || []).filter((it) => (num ? String(it.number).startsWith(num[1])
    : q.split(/\s+/).every((w) => it.title.toLowerCase().includes(w) || it.labels.some((l) => l.toLowerCase().includes(w)))));
}
const HINTS = {
  'implement-issue': '5940, or an issue URL',
  'pr-grind': 'The Slack link of the review thread',
  worklog: '2026-10-08',
  'pr-review': '5960, or a PR URL',
};
const OPTIONAL_ARGS = new Set(['worklog', 'day', 'verifier-locally', 'docs-updater', 'sync-from-wasensi', 'peer-review', 'release-pr']);
// These take a written description rather than a number or link, so they get room to write.
export const FREE_TEXT = new Set(['create-prd', 'dump', 'day', 'flow', 'skill-feedback']);
const URL_KIND = { 'implement-issue': 'issues', 'pr-grind': 'pull' };

export function repoOptions(body) {
  const list = body && Array.isArray(body.repos) ? body.repos : [];
  return list
    .filter((r) => r && typeof r.slug === 'string' && typeof r.path === 'string')
    .map((r) => ({ value: r.slug, label: `${r.name || r.slug} - ${r.path}`, name: r.name || r.slug, path: r.path }));
}

// New run and Flow keep { repos, repo, manual, path, canBrowse } in their state; this renders the
// shared RepoPicker over it. A picked path sets manual mode; a picked repo clears it.
// allowVault adds "No repo yet" (state.vault); allowCreate adds "Create a new repo…" (state.creating).
export function hostRepoPicker(host, s, { id, error, after, allowVault = false, allowCreate = false }) {
  return html`<${RepoPicker} id=${id} repos=${s.repos} value=${{ repo: s.manual ? '' : s.repo, path: s.manual ? s.path : '', vault: !!(allowVault && s.vault) }}
    allowPath=${true} canBrowse=${s.canBrowse} error=${error} allowVault=${allowVault} allowCreate=${allowCreate}
    onCreate=${() => host.setState({ creating: true })}
    onPick=${(sel) => host.setState(sel.vault ? { vault: true } : sel.path ? { vault: false, manual: true, path: sel.path } : { vault: false, manual: false, repo: sel.repo, path: '' }, after)} />`;
}

// A repo made by Create repo joins the list and becomes the choice.
export async function adoptCreatedRepo(host, made) {
  let repos = host.state.repos;
  try {
    const r = await fetch('/api/repos', { headers: { Accept: 'application/json' } });
    if (r.ok) repos = repoOptions(await r.json());
  } catch { /* keep the old list; the new slug is still selected */ }
  host.setState({ repos, repo: made.slug, manual: false, path: '', vault: false, creating: false });
}

// The no-repo fields a request carries when "No repo yet" is chosen.
export const vaultBody = (s) => (s.vault ? { repo: '', no_repo: true, ...(folderOf(s.vf) ? { vault_folder: folderOf(s.vf) } : {}) } : {});

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

export function validate({ repo, path, manual, command, args, vault }) {
  const errors = {};
  if (vault && !NO_REPO_COMMANDS.has(command)) errors.repo = `${command} needs a repo: pick one, or use create-prd, dump or a custom prompt for a new idea`;
  else if (!vault && !String((manual ? path : repo) ?? '').trim()) errors.repo = 'Choose a repo or enter a path';
  if (!OPTIONAL_ARGS.has(command) && !String(args ?? '').trim()) errors.args = `Enter ${LABELS[command].toLowerCase()}`;
  return Object.keys(errors).length ? errors : null;
}

export function validateCustom({ repo, path, manual, text, vault }, lenses) {
  const errors = {};
  if (!vault && !String((manual ? path : repo) ?? '').trim()) errors.repo = 'Choose a repo or enter a path';
  if (!String(text ?? '').trim()) errors.text = 'Enter a command or prompt';
  if (lenses && !lenses.length) errors.customLenses = 'Tick at least one reviewer';
  return Object.keys(errors).length ? errors : null;
}

// Peer review: the lenses each command offers come from GET /api/peer-review, never hardcoded.
const LENS_NAMES = { ceo: 'CEO', cto: 'CTO', qa: 'QA', ux: 'UX' };
export const lensName = (l) => LENS_NAMES[l] || l.charAt(0).toUpperCase() + l.slice(1);

export function toggleLens(picked, lens, on, offer) {
  const s = new Set(picked);
  if (on) s.add(lens);
  else s.delete(lens);
  return offer.filter((l) => s.has(l)); // keep the config's order
}

// null when review is off; otherwise the lenses to send (an empty list is a validation error)
export function pickedLenses(on, picked, offers) {
  return on === true ? picked || (offers && offers.default) || [] : null;
}

export function lensPicker({ id, offer, on, picked, rounds, disabled, onToggle, onPick }) {
  if (!offer || !offer.length) return null;
  return html`<div class="lens-pick">
    <label class="check" for=${id}><input id=${id} type="checkbox" checked=${on === true} disabled=${disabled}
      onChange=${(e) => onToggle(e.target.checked)} /> Peer review: each ticked reviewer must approve (up to ${rounds || 5} rounds, on Opus)</label>
    ${on === true && html`<fieldset class="lenses"><legend>Reviewers</legend>
      ${offer.map((l) => html`<label class="check" for=${id + '-' + l}><input id=${id + '-' + l} type="checkbox"
        checked=${(picked || []).includes(l)} disabled=${disabled}
        onChange=${(e) => onPick(toggleLens(picked || [], l, e.target.checked, offer))} /> ${lensName(l)}</label>`)}
    </fieldset>`}
  </div>`;
}

export function buildCustomBody({ repo, text, lenses }) {
  const body = { repo, text: String(text).trim() };
  if (lenses) body.peer_review = lenses; // the server adds a review line to the prompt
  return body;
}

export function buildBody({ repo, command, args, lenses }) {
  const a = String(args).trim();
  const body = { repo, command, args: a };
  if (lenses) body.peer_review = lenses; // the server appends --review <lenses>
  const issue = command === 'pr-grind' ? argIssue(command, a) : null;
  if (issue) body.issue = issue;
  return body;
}

// Every start lands on the sessions list: the run page is gone and a session has no id until it lists.
export function sessionHref() {
  return '#/sessions';
}

export function outcome(status, body, command) {
  const err = body && typeof body.error === 'string' ? body.error : `Request failed (HTTP ${status})`;
  if (status === 201) return { kind: 'open', href: sessionHref(body, command) };
  if (status === 409) return { kind: 'duplicate', message: err, href: sessionHref(body, command) };
  if (status === 400 && err.startsWith('not a git repository')) return { kind: 'repo', message: err };
  return { kind: 'error', message: err };
}

export const loadLastRepo = (storage) => loadPref(storage, KEY) || null;
export const saveLastRepo = (storage, value) => savePref(storage, KEY, value);

// The argument after switching command. Free text carries over to free text. An issue or PR
// carries over to a command taking the same kind, rewritten in that command's form (12, o/r#12 or
// the URL); search words carry over as typed. Anything else would not parse, so it is cleared.
export function switchArgs(from, to, args, slug, items) {
  if (FREE_TEXT.has(from) && FREE_TEXT.has(to)) return args;
  if (!PICK[from] || PICK[from] !== PICK[to]) return '';
  const n = typedNumber(args);
  if (n == null) return args;
  // A reference to another repo is kept exactly as typed, never moved onto the selected repo.
  const named = /(?:\/\/[^/\s]+\/|^)([\w.-]+\/[\w.-]+)(?:\/(?:issues|pull)\/\d+|#\d+)\/?$/.exec(String(args).trim());
  if (named && named[1].toLowerCase() !== String(slug).toLowerCase()) return args;
  // No repo to rewrite against (a manual path): keep it only if the new command takes the same form.
  if (!slug) return pickValue(to, 'x/x', { number: n }) === pickValue(from, 'x/x', { number: n }) ? args : '';
  return pickValue(to, slug, (items || []).find((it) => it.number === n) || { number: n });
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
  state = { repos: [], repo: '', manual: false, path: '', command: COMMANDS.includes(loadPref(globalThis.localStorage, CMD_KEY)) ? loadPref(globalThis.localStorage, CMD_KEY) : 'implement-issue', args: '', text: '', pending: false, errors: {}, result: null, form: 'named', canBrowse: false };

  async componentDidMount() {
    fetch('/api/settings', { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .then((s) => s && this.setState({ cmds: s.commands || [], claudeLabel: s.default || '' }))
      .catch(() => {}); // no picker without settings: runs use claude
    fetch('/api/peer-review', { headers: { Accept: 'application/json' } })
      .then((r) => (r.ok ? r.json() : null))
      .then((o) => o && this.setState({ offers: o }))
      .catch(() => {}); // no peer review picker without offers
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
    const repo = this.repoValue();
    this.setState({ pending: true, form, errors: {}, result: null });
    const r = await this.post(mkBody(repo));
    if (!r) return;
    this.setState({ pending: false, result: r.kind === 'open' ? null : r });
    if (r.kind === 'open') {
      this.remember(repo, form);
      toast('Session started');
      location.hash = r.href;
    }
  };

  repoValue = () => (this.state.manual || !this.state.repos.length ? this.state.path : this.state.repo).trim();

  // The one way a New run body goes out: the form's run options added, through one in-flight guard.
  post = (body) => {
    const s = this.state;
    this.submit = this.submit || makeSubmitter((...a) => fetch(...a));
    return this.submit({ ...body, ...vaultBody(s), ...(s.claudeLabel ? { claude_cmd: s.claudeLabel } : {}) });
  };

  remember = (repo, form) => {
    if (repo) saveLastRepo(globalThis.localStorage, repo);
    if (form === 'named') savePref(globalThis.localStorage, CMD_KEY, this.state.command);
  };

  openCache = new Map();

  componentDidUpdate() {
    this.loadOpen();
  }

  // The selected repo's open issues or PRs for the picker, fetched once per repo and kind.
  loadOpen = (force = false) => {
    const { command, repo, manual } = this.state;
    const kind = PICK[command];
    if (!kind || manual || !repo) return;
    const key = `${repo}|${kind}`;
    if (!force && this.openCache.has(key)) return;
    this.openCache.set(key, { status: 'loading', items: (this.openCache.get(key) || {}).items || [] });
    if (this.state.openKey !== key || force) this.setState({ openKey: key });
    const [owner, name] = repo.split('/');
    fetch(`/api/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/open?kind=${kind}`, { headers: { Accept: 'application/json' } })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        this.openCache.set(key, r.ok ? { status: 'ok', items: body.items || [] } : { status: 'error', items: [], error: body.error || `HTTP ${r.status}` });
      })
      .catch(() => this.openCache.set(key, { status: 'error', items: [], error: 'could not reach the aiw server' }))
      .finally(() => this.setState({ openTick: (this.state.openTick || 0) + 1 }));
  };

  worklogPicker() {
    const { wlMode = 'today', wlDay = '', wlFrom = '', wlTo = '', errors } = this.state;
    const today = isoDay(new Date());
    const set = (patch) => this.setState({ ...patch, wlFailed: null, errors: { ...errors, args: undefined } });
    const wl = worklogDates({ mode: wlMode, day: wlDay, from: wlFrom, to: wlTo }, today);
    const aria = { 'aria-invalid': errors.args ? 'true' : undefined, 'aria-describedby': errors.args ? 'args-error' : undefined };
    return html`<fieldset class="wl">
      <legend>Which day</legend>
      <div class="seg" role="radiogroup" aria-label="Which day">
        ${[['today', 'Today'], ['yesterday', 'Yesterday'], ['day', 'A day'], ['range', 'A range']].map(([m, l]) => html`<button type="button" role="radio"
          aria-checked=${wlMode === m} class=${wlMode === m ? 'on' : ''} onClick=${() => set({ wlMode: m })}>${l}</button>`)}
      </div>
      ${wlMode === 'day' && html`<label class="wl-date" for="args">Day <input id="args" type="date" max=${today} value=${wlDay} onInput=${(e) => set({ wlDay: e.target.value })} ...${aria} /></label>`}
      ${wlMode === 'range' && html`<div class="wl-range">
        <label class="wl-date" for="args">From <input id="args" type="date" max=${wlTo || today} value=${wlFrom} onInput=${(e) => set({ wlFrom: e.target.value })} ...${aria} /></label>
        <label class="wl-date" for="wl-to">To <input id="wl-to" type="date" min=${wlFrom || undefined} max=${today} value=${wlTo} onInput=${(e) => set({ wlTo: e.target.value })} ...${aria} /></label>
      </div>`}
      ${wlMode === 'range' && wl.dates && html`<p class="note">${wl.dates.length} day${wl.dates.length === 1 ? '' : 's'}: ${wl.dates.length === 1 ? 'one worklog run' : `${wl.dates.length} worklog runs, 3 at a time (the rest start as those finish)`}, one daily note each.</p>`}
    </fieldset>`;
  }

  pickList() {
    const { command, repo, manual, args } = this.state;
    const kind = PICK[command];
    if (!kind || manual || !repo) return null;
    const got = this.openCache.get(`${repo}|${kind}`) || { status: 'loading', items: [] };
    const noun = kind === 'pr' ? 'PRs' : 'issues';
    const chosen = typedNumber(args);
    const shown = matchItems(got.items, args);
    const hit = got.items.find((it) => it.number === chosen);
    // One tab stop for the whole list; arrows move between rows, as in the repo picker.
    const pickKeys = (e) => {
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      const li = e.target.closest('li');
      const next = li && (e.key === 'ArrowDown' ? li.nextElementSibling : li.previousElementSibling);
      if (next) {
        e.preventDefault();
        next.querySelector('button').focus();
      }
    };
    return html`<div class="pick">
      <div class="pick-head"><span>${got.status === 'ok' ? `Open ${noun} · ${got.items.length}` : `Open ${noun}`}</span>
        <button type="button" class="linkish" disabled=${got.status === 'loading'} onClick=${() => this.loadOpen(true)}>${got.status === 'loading' ? 'Loading…' : 'Refresh'}</button></div>
      ${hit && html`<p class="pick-chosen" role="status">Selected <b>#${hit.number}</b> ${hit.title}</p>`}
      ${got.status === 'error' ? html`<p class="note">Could not list ${noun}: ${String(got.error).replace(/\.+$/, '')}. Type a number or URL instead.</p>`
        : got.status === 'ok' && !got.items.length ? html`<p class="note">No open ${noun} in ${repo}.</p>`
        : got.items.length && !shown.length ? html`<p class="note">No open ${noun} match. A number or URL still works.</p>`
        : got.items.length > 0 && html`<ul class="pick-list" aria-label=${`Open ${noun}`} onKeyDown=${pickKeys}>
          ${shown.slice(0, 50).map((it, i) => html`<li key=${it.number}><button type="button" class=${it.number === chosen ? 'pick-item on' : 'pick-item'} aria-pressed=${it.number === chosen ? 'true' : 'false'}
            tabIndex=${(shown.some((x) => x.number === chosen) ? it.number === chosen : i === 0) ? 0 : -1}
            onClick=${() => this.setState({ args: pickValue(command, repo, it), errors: { ...this.state.errors, args: undefined } }, () => document.getElementById('args')?.focus())}>
            <span class="mono">#${it.number}</span><span class="pick-title">${it.title}</span>
            ${it.draft && html`<span class="chip other">draft</span>`}
            ${it.labels.slice(0, 3).map((l) => html`<span class="pick-label">${l}</span>`)}
          </button></li>`)}
        </ul>`}
    </div>`;
  }


  // Typing an issue/PR link picks its repo from the dropdown when it is registered.
  setText = (k) => (e) => {
    const v = e.target.value;
    const hit = repoFromText(this.state.repos, v);
    this.setState({ [k]: v, ...(hit ? { repo: hit, manual: false } : {}) });
  };

  reviewOffer = (kind) => (this.state.offers && this.state.offers.kinds[kind]) || null;

  namedLenses = () => (this.reviewOffer(this.state.command) ? pickedLenses(this.state.peerReview, this.state.lenses, this.state.offers) : null);

  customLenses = () => pickedLenses(this.state.customReview, this.state.customPicked, this.state.offers);

  // Worklog: one run, or one per day of a range (each writes its own daily note). A range shares a
  // batch id, so the server runs 3 days at a time and starts the rest as those finish.
  onWorklog = async (ev) => {
    ev.preventDefault();
    const s = this.state;
    if (s.pending) return;
    const repoErr = validate({ ...s, args: 'x' });
    const wl = s.wlFailed?.length ? { dates: s.wlFailed } : worklogDates({ mode: s.wlMode, day: s.wlDay, from: s.wlFrom, to: s.wlTo }, isoDay(new Date()));
    if (repoErr || wl.error) return this.setState({ errors: { ...(repoErr || {}), ...(wl.error ? { args: wl.error } : {}) }, result: null });
    if (wl.dates.length === 1 && !s.wlFailed?.length) return this.start(ev, 'named', null, (repo) => buildBody({ repo, command: 'worklog', args: wl.dates[0] }));
    const repo = this.repoValue();
    const batch = `wl-${Date.now().toString(36)}`;
    this.setState({ pending: true, form: 'named', errors: {}, result: null });
    let ok = 0;
    const failed = [];
    for (const [i, date] of wl.dates.entries()) {
      this.setState({ progress: `Starting ${i + 1} of ${wl.dates.length}…` });
      const r = await this.post({ ...buildBody({ repo, command: 'worklog', args: date }), batch });
      if (r && r.kind === 'open') ok++;
      else failed.push({ date, why: (r && r.message) || 'failed' });
    }
    this.setState({
      pending: false,
      progress: null,
      wlFailed: failed.map((f) => f.date),
      result: failed.length ? { kind: 'error', message: `${failed.length} of ${wl.dates.length} did not start: ${failed.map((f) => `${f.date} (${f.why})`).join('; ')}` } : null,
    });
    if (ok) {
      this.remember(repo, 'named');
      toast(`Started ${ok} worklog run${ok === 1 ? '' : 's'}, 3 at a time`);
      if (!failed.length) location.hash = '#/sessions';
    }
  };

  onSubmit = (ev) => {
    if (this.state.command === 'worklog') return this.onWorklog(ev);
    const lenses = this.namedLenses();
    const errors = validate(this.state) || (lenses && !lenses.length ? { lenses: 'Tick at least one reviewer' } : null);
    return this.start(ev, 'named', errors, (repo) => buildBody({ repo, command: this.state.command, args: this.state.args, lenses }));
  };

  onCustom = (ev) => {
    const lenses = this.customLenses();
    return this.start(ev, 'custom', validateCustom(this.state, lenses), (repo) => buildCustomBody({ repo, text: this.state.text, lenses }));
  };

  render({ limits }, { canBrowse, cmds, claudeLabel, repos, repo, manual, path, command, args, text, pending, form, errors, result, offers }) {
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
        ${hostRepoPicker(this, { repos, repo, manual, path, canBrowse, vault: this.state.vault }, { id: 'repo-path', error: repoMsg ? 'repo-error' : null, allowVault: true, allowCreate: true, after: () => this.setState({ errors: { ...this.state.errors, repo: undefined }, result: null }) })}
        ${repoMsg ? html`<p id="repo-error" role="alert" class="error">${repoMsg}</p>` : null}
        ${this.state.vault && !NO_REPO_COMMANDS.has(command) && !repoMsg && html`<p class="note">${command} needs a repo. With no repo yet, use create-prd or dump here, or the custom prompt.</p>`}
        ${this.state.vault && html`<${FolderChooser} id="vf" text=${NO_REPO_COMMANDS.has(command) && args.trim() ? args : text} value=${this.state.vf || { project: '', feature: '' }}
          onChange=${(vf) => this.setState({ vf })} />`}
        ${this.state.creating && html`<${CreateRepoDialog} withPrd=${false} onClose=${() => this.setState({ creating: false })} onDone=${(made) => adoptCreatedRepo(this, made)} />`}
        <fieldset class="cmds">
          <legend>Command</legend>
          ${GROUPS.map(([group, cmds]) => html`<div class="cmd-group" role="group" aria-label=${group}>
            <span class="cmd-group-name" aria-hidden="true">${group}</span>
            ${cmds.map(([c, desc]) => html`<label for=${'cmd-' + c} class="radio cmd-opt">
              <input id=${'cmd-' + c} type="radio" name="command" value=${c} checked=${command === c} onChange=${(e) => this.setState({ command: e.target.value, args: switchArgs(command, e.target.value, args, manual ? '' : repo, (this.openCache.get(`${repo}|${PICK[command]}`) || {}).items), errors: { ...errors, args: undefined } })} />
              <span class="cmd-text"><span class="cmd-name">${c}</span><span class="cmd-desc">${desc}</span></span></label>`)}
          </div>`)}
        </fieldset>
        ${command === 'worklog' ? this.worklogPicker() : html`<label for="args">${LABELS[command]}</label>`}
        ${command === 'worklog' ? null : FREE_TEXT.has(command)
          ? html`<textarea id="args" class="args-text" rows="8" value=${args} onInput=${this.setText('args')}
              onKeyDown=${(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); e.target.form.requestSubmit(); } }}
              aria-invalid=${errors.args ? 'true' : undefined} aria-describedby=${errors.args ? 'args-error' : undefined}></textarea>`
          : html`<input id="args" type="text" autocomplete="off" placeholder=${PICK[command] && !manual ? `${HINTS[command] || ''}, or type to search the list below` : HINTS[command] || ''} value=${args} onInput=${this.setText('args')}
              aria-invalid=${errors.args ? 'true' : undefined} aria-describedby=${errors.args ? 'args-error' : undefined} />`}
        ${errors.args ? html`<p id="args-error" role="alert" class="error">${errors.args}</p>` : null}
        ${this.pickList()}
        ${limitedUntil(cmds, claudeLabel, limits) ? html`<p class="note">This account is rate limited: the run is queued and starts automatically at reset.</p>` : null}
        ${lensPicker({ id: 'peer-review', offer: this.reviewOffer(command), on: this.state.peerReview, picked: pickedLenses(true, this.state.lenses, offers), rounds: offers && offers.max_rounds,
          onToggle: (on) => this.setState({ peerReview: on }), onPick: (lenses) => this.setState({ lenses }) })}
        ${errors.lenses ? html`<p role="alert" class="error">${errors.lenses}</p>` : null}
        ${outcomeMsg('named')}
        <div class="launch-actions">
          <button type="submit" disabled=${pending}>${pending && (form || 'named') === 'named' ? this.state.progress || 'Starting...' : command === 'worklog' && this.state.wlFailed?.length ? `Retry ${this.state.wlFailed.length} failed day${this.state.wlFailed.length === 1 ? '' : 's'}` : 'Start'}${FREE_TEXT.has(command) && html` <kbd>⌘↵</kbd>`}</button>
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
        <textarea id="custom" placeholder="/pr-review 42" value=${text} onInput=${this.setText('text')}
          aria-invalid=${errors.text ? 'true' : undefined} aria-describedby=${errors.text ? 'custom-error' : undefined}></textarea>
        ${errors.text ? html`<p id="custom-error" role="alert" class="error">${errors.text}</p>` : null}
        <p class="note danger">Runs with --dangerously-skip-permissions: the command or prompt is not gated.</p>
        ${lensPicker({ id: 'custom-review', offer: this.reviewOffer('custom'), on: this.state.customReview, picked: pickedLenses(true, this.state.customPicked, offers), rounds: offers && offers.max_rounds,
          onToggle: (on) => this.setState({ customReview: on }), onPick: (customPicked) => this.setState({ customPicked }) })}
        ${this.state.customReview === true && html`<p class="note">The session is asked to run the review when it's done; it isn't forced. The session shows whether it ran.</p>`}
        ${errors.customLenses ? html`<p role="alert" class="error">${errors.customLenses}</p>` : null}
        ${outcomeMsg('custom')}
        <button type="submit" disabled=${pending}>${pending && form === 'custom' ? 'Starting...' : 'Run in selected repo'}</button>
      </form>
      </aside>
      </div>
    `;
  }
}
