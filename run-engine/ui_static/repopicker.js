import { h, Component } from './vendor/preact.mjs';
import htm from './vendor/htm.mjs';
import { loadPref, savePref } from './fmt.js';
import { toast } from './toast.js';

const html = htm.bind(h);
const RECENT_KEY = 'aiw.recentRepos';
const RECENT_MAX = 4;

// The one repo picker: New run, Flow, Dispatch and the Board filter all use it, so a repo is
// chosen the same way everywhere. A button shows the choice; it opens a searchable list with the
// recently used repos first, a typed absolute path (where the host allows one) and the native
// folder dialog. Hosts own the value ({ repo: slug, path }) and hear about changes via onPick.

// A typed absolute path is usable as-is; the server validates that it is a git checkout.
export function pathOption(query) {
  const q = String(query ?? '').trim();
  return q.startsWith('/') ? q : null;
}

// Every word must appear in the slug, name or path; repos whose repo or project name starts with the query rank first.
export function matchRepos(repos, query) {
  const q = String(query ?? '').trim().toLowerCase();
  if (!q) return repos;
  const words = q.split(/\s+/);
  const hits = repos.filter((r) => words.every((w) => `${r.value} ${r.name} ${r.path}`.toLowerCase().includes(w)));
  const lead = (r) => r.value.split('/').pop().toLowerCase().startsWith(q) || r.name.toLowerCase().startsWith(q);
  return [...hits.filter(lead), ...hits.filter((r) => !lead(r))];
}

export function loadRecent(storage) {
  try {
    const list = JSON.parse(loadPref(storage, RECENT_KEY) || '[]');
    return Array.isArray(list) ? list.filter((s) => typeof s === 'string') : [];
  } catch {
    return [];
  }
}

export function pushRecent(storage, slug) {
  if (!slug) return;
  savePref(storage, RECENT_KEY, JSON.stringify([slug, ...loadRecent(storage).filter((s) => s !== slug)].slice(0, RECENT_MAX)));
}

// The rows of the open list, in order: [{ kind: 'all'|'vault'|'repo'|'path'|'browse'|'create', group?, repo?, path? }].
// allowVault offers "No repo yet" (a new idea, run in the notes vault); allowCreate ends the list
// with "Create a new repo…".
export function pickerRows({ repos, query, recent = [], allLabel, allowPath, canBrowse, allowVault, allowCreate }) {
  const rows = [];
  const q = String(query ?? '').trim();
  if (allLabel && !q) rows.push({ kind: 'all' });
  if (allowVault && (!q || /^(no|new|idea|vault|none)/i.test(q))) rows.push({ kind: 'vault' });
  const shown = matchRepos(repos, q);
  const recents = q ? [] : recent.map((s) => repos.find((r) => r.value === s)).filter(Boolean);
  for (const r of recents) rows.push({ kind: 'repo', group: 'Recent', repo: r });
  for (const r of shown) if (!recents.includes(r)) rows.push({ kind: 'repo', group: recents.length ? 'All repos' : null, repo: r });
  const path = allowPath ? pathOption(q) : null;
  if (path && !repos.some((r) => r.path === path)) rows.push({ kind: 'path', path });
  if (allowPath && canBrowse) rows.push({ kind: 'browse' });
  if (allowCreate) rows.push({ kind: 'create' });
  return rows;
}

// GET /api/repos for views that only need the list (the Board filter). `fresh` refetches, so a repo
// registered while the page was open shows up the next time the Board mounts.
let listing = null;
export function loadRepoList(fresh = false) {
  listing = (!fresh && listing) || fetch('/api/repos', { headers: { Accept: 'application/json' } })
    .then((r) => (r.ok ? r.json() : null))
    .then((b) => (b && Array.isArray(b.repos) ? b.repos.filter((r) => r && typeof r.slug === 'string') : []))
    .catch(() => { listing = null; return []; }); // a failed load is retried on the next call
  return listing;
}

const owner = (slug) => String(slug).split('/')[0];
const short = (slug) => String(slug).split('/').pop();
// The repo's own name leads (names are unique per owner; worklog project names are not), then the
// owner and, when it differs, the project name.
const sub = (r) => owner(r.value) + (r.name && ![r.value, short(r.value)].map((x) => x.toLowerCase()).includes(r.name.toLowerCase()) ? ` · ${r.name}` : '');

export class RepoPicker extends Component {
  state = { open: false, query: '', active: 0, browsing: false };

  componentWillUnmount() {
    document.removeEventListener('mousedown', this.outside);
  }

  // Once the list is on screen, typing goes to its search box; a tick later, so the click that
  // opened it cannot take focus back.
  componentDidUpdate(_, prev) {
    if (this.state.open && !prev.open) {
      setTimeout(() => {
        const box = this.root && this.root.querySelector('.rp-search');
        if (box) box.focus();
        this.reveal();
      }, 0);
    }
  }

  outside = (e) => {
    if (this.root && !this.root.contains(e.target)) this.close(false);
  };

  open = () => {
    if (this.props.disabled) return;
    const { value } = this.props;
    const rows = pickerRows({ ...this.props, query: '', recent: loadRecent(globalThis.localStorage) });
    // Open on the current choice, so Enter keeps it and arrows move from it.
    const at = rows.findIndex((r) => (r.kind === 'vault' && value.vault) || (!value.vault && ((r.kind === 'repo' && !value.path && r.repo.value === value.repo) || (r.kind === 'all' && !value.repo && !value.path))));
    this.setState({ open: true, query: '', active: Math.max(0, at) });
    document.addEventListener('mousedown', this.outside);
  };

  close = (refocus = true) => {
    document.removeEventListener('mousedown', this.outside);
    this.setState({ open: false, query: '' }, () => refocus && this.root?.querySelector('.rp-trigger')?.focus());
  };

  choose = (sel) => {
    if (sel.vault) {
      this.close();
      this.props.onPick({ repo: '', path: '', vault: true });
      return;
    }
    // A path that is a registered checkout is that repo: one name for one place.
    const known = sel.path && this.props.repos.find((r) => r.path === sel.path);
    const pick = known ? { repo: known.value, path: '' } : { repo: sel.repo, path: sel.path };
    if (pick.repo && !this.props.allLabel) pushRecent(globalThis.localStorage, pick.repo);
    this.close();
    this.props.onPick(pick);
  };

  browse = async () => {
    const { repos, value } = this.props;
    const start = value.path || (repos.find((r) => r.value === value.repo) || {}).path || '';
    this.setState({ browsing: true });
    try {
      const res = await fetch('/api/repos/browse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ start }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const { path } = await res.json();
      if (path) this.choose({ repo: '', path });
    } catch {
      toast('Could not open the folder picker');
    } finally {
      this.setState({ browsing: false });
    }
  };

  rows() {
    const { repos, allLabel, allowPath, canBrowse, allowVault, allowCreate } = this.props;
    return pickerRows({ repos, query: this.state.query, recent: loadRecent(globalThis.localStorage), allLabel, allowPath, canBrowse, allowVault, allowCreate });
  }

  act = (row) => {
    if (row.kind === 'all') this.choose({ repo: '', path: '' });
    else if (row.kind === 'repo') this.choose({ repo: row.repo.value, path: '' });
    else if (row.kind === 'path') this.choose({ repo: '', path: row.path });
    else if (row.kind === 'vault') this.choose({ vault: true });
    else if (row.kind === 'create') {
      this.close();
      this.props.onCreate?.();
    } else this.browse();
  };

  key = (e) => {
    const rows = this.rows();
    const n = rows.length;
    const { active } = this.state;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (n) this.setState({ active: (active + (e.key === 'ArrowDown' ? 1 : n - 1)) % n }, this.reveal);
    } else if (e.key === 'Home' || e.key === 'End') {
      e.preventDefault();
      this.setState({ active: e.key === 'Home' ? 0 : Math.max(0, n - 1) }, this.reveal);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (n) this.act(rows[Math.min(active, n - 1)]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation(); // the picker eats this Esc, not the page's "go back"
      this.close();
    } else if (e.key === 'Tab') this.close(false);
  };

  reveal = () => this.root?.querySelector('.rp-list [aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });

  label({ repos, value, allLabel, placeholder }) {
    if (value.vault) return html`<span class="rp-icon" aria-hidden="true">✦</span><span class="rp-name">No repo yet</span><span class="rp-sub">a new idea, in your notes vault</span>`;
    if (value.path) return html`<span class="rp-icon" aria-hidden="true">▤</span><span class="rp-name">${value.path.split('/').filter(Boolean).pop() || '/'}</span><span class="rp-sub mono">${value.path}</span>`;
    const r = repos.find((x) => x.value === value.repo);
    if (r) return html`<span class="rp-name">${short(r.value)}</span><span class="rp-sub">${sub(r)}</span>`;
    if (value.repo) return html`<span class="rp-name">${value.repo.split('/').pop()}</span><span class="rp-sub">${owner(value.repo)}</span>`;
    return html`<span class="rp-placeholder">${allLabel || placeholder || 'Choose a repo'}</span>`;
  }

  // The trigger's accessible name says the field and the choice ("Repo: bop-bd"); a <label for> alone
  // would replace the button's content and hide which repo is selected.
  spoken({ repos, value, allLabel, placeholder, label = 'Repo' }) {
    if (value.vault) return `${label}: no repo yet, the notes vault`;
    const r = repos.find((x) => x.value === value.repo);
    const what = value.path || (r ? `${short(r.value)}, ${owner(r.value)}` : value.repo ? short(value.repo) : allLabel || placeholder || 'none chosen');
    return `${label}: ${what}`;
  }

  render({ id, repos, value, allLabel, allowPath, error, disabled, placeholder, label }, { open, query, active, browsing }) {
    const list = `${id}-list`;
    const rows = open ? this.rows() : [];
    const current = (r) => (r.kind === 'vault' && value.vault) || (!value.vault && ((r.kind === 'repo' && !value.path && r.repo.value === value.repo) || (r.kind === 'all' && !value.repo && !value.path)));
    let lastGroup = null;
    // A ref, not this.base: preact 11 no longer sets base on components.
    return html`<div class=${open ? 'rp open' : 'rp'} ref=${(el) => { this.root = el; }}>
      <button type="button" id=${id} class="rp-trigger" aria-label=${this.spoken({ repos, value, allLabel, placeholder, label })} aria-haspopup="listbox" aria-expanded=${open ? 'true' : 'false'} disabled=${disabled}
        title=${value.path || (repos.find((r) => r.value === value.repo) || {}).path || ''}
        aria-invalid=${error ? 'true' : undefined} aria-describedby=${error || undefined}
        onClick=${() => (open ? this.close() : this.open())}
        onKeyDown=${(e) => { if (!open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { e.preventDefault(); this.open(); } }}>
        ${this.label({ repos, value, allLabel, placeholder })}<span class="rp-chev" aria-hidden="true"></span>
      </button>
      ${open && html`<div class="rp-pop">
        <input type="text" class="rp-search" role="combobox" autocomplete="off" spellcheck="false" aria-label="Search repos"
          aria-expanded="true" aria-controls=${list} aria-autocomplete="list" aria-activedescendant=${rows.length ? `${id}-opt-${Math.min(active, rows.length - 1)}` : undefined}
          placeholder=${allowPath ? 'Search repos, or type an absolute path' : 'Search repos'} value=${query}
          onInput=${(e) => this.setState({ query: e.target.value, active: 0 })} onKeyDown=${this.key} />
        <ul id=${list} class="rp-list" role="listbox" aria-label="Repos">
          ${rows.map((r, i) => {
            const head = r.group && r.group !== lastGroup ? html`<li class="rp-group" role="presentation">${r.group}</li>` : null;
            lastGroup = r.group || lastGroup;
            return html`${head}<li id=${`${id}-opt-${i}`} role="option" key=${i} aria-selected=${i === active ? 'true' : 'false'}
              class=${`rp-opt rp-${r.kind}${current(r) ? ' current' : ''}`}
              onMouseDown=${(e) => e.preventDefault()} onMouseEnter=${() => this.setState({ active: i })} onClick=${() => this.act(r)}>
              ${r.kind === 'all' ? html`<span class="rp-name">${allLabel}</span>`
                : r.kind === 'repo' ? html`<span class="rp-name">${short(r.repo.value)}</span><span class="rp-sub">${sub(r.repo)}</span>${r.repo.path && html`<small class="mono">${r.repo.path}</small>`}`
                : r.kind === 'path' ? html`<span class="rp-name">Use this path</span><small class="mono">${r.path}</small>`
                : r.kind === 'vault' ? html`<span class="rp-name">No repo yet</span><span class="rp-sub">a new idea</span><small>${'Runs in your notes vault and files under 05-Work/<Project>/<Feature>'}</small>`
                : r.kind === 'create' ? html`<span class="rp-name">Create a new repo…</span><small>A local git repo with a README, in a folder you pick</small>`
                : html`<span class="rp-name">${browsing ? 'Opening folder picker…' : 'Browse for a folder…'}</span><small>Pick any git checkout on this Mac</small>`}
            </li>`;
          })}
          ${!rows.some((r) => r.kind === 'repo' || r.kind === 'path') && html`<li class="rp-empty" role="presentation">
            ${repos.length ? 'No repos match.' : 'No repos registered yet.'}${allowPath ? ' Type an absolute path to a git checkout.' : ' Start a run once to register one.'}</li>`}
        </ul>
      </div>`}
    </div>`;
  }
}
