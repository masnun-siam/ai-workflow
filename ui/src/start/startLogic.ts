// Pure helpers for the Start dialog (FR-22): request bodies, worklog days, issue/PR argument handling, vault folders.
// Ported from the old launcher.js / vault.js so the request bodies stay what the server expects.
import type { Limit, OpenItem, Repo, SessionStartBody } from '../api/types';
import type { ArgKind } from '../lib/vocab';

/** Commands the server lets run with no repo (ui_repos.start_session): create-prd, dump, a custom prompt. */
export const NO_REPO = new Set(['create-prd', 'dump', 'day', 'custom']);
/** Commands whose argument may stay empty. */
export const OPTIONAL = new Set(['peer-review', 'day']);
export const CMD_KEY = 'aiw.lastCommand';

// ---- worklog days ---------------------------------------------------------------------------------
export const WORKLOG_MAX_DAYS = 31;
export const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const dayAfter = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number);
  return isoDay(new Date(y, m - 1, d + 1));
};
export interface WorklogPick {
  mode: 'today' | 'yesterday' | 'day' | 'range';
  day: string;
  from: string;
  to: string;
}
/** The dates to run (`today`/`yesterday` pass through as words), or an error. `today` is the local date. */
export function worklogDates(p: WorklogPick, today: string): { dates: string[] } | { error: string } {
  if (p.mode === 'today' || p.mode === 'yesterday') return { dates: [p.mode] };
  if (p.mode === 'day') {
    if (!p.day) return { error: 'Pick a day' };
    return p.day > today ? { error: 'Pick a day that has happened' } : { dates: [p.day] };
  }
  if (!p.from || !p.to) return { error: 'Pick both the first and the last day' };
  if (p.from > p.to) return { error: 'The first day must come before the last' };
  if (p.to > today) return { error: 'The last day cannot be in the future' };
  const dates: string[] = [];
  for (let d = p.from; d <= p.to && dates.length <= WORKLOG_MAX_DAYS; d = dayAfter(d)) dates.push(d);
  return dates.length > WORKLOG_MAX_DAYS ? { error: `Pick at most ${WORKLOG_MAX_DAYS} days` } : { dates };
}

// ---- issue / PR arguments -------------------------------------------------------------------------
/** The command's open-item list: implement-issue lists issues, the review commands list PRs. */
export const PICK: Record<string, 'issue' | 'pr'> = { 'implement-issue': 'issue', 'pr-review': 'pr', 'pr-grind': 'pr' };

/** What a picked item writes into the argument: pr-grind takes the PR's URL, the rest a bare number. */
export const pickValue = (command: string, item: Pick<OpenItem, 'number' | 'url'>) =>
  command === 'pr-grind' && item.url ? item.url : String(item.number);

/** The number the argument names: `12`, `#12`, or an issue/PR URL. */
export function typedNumber(args: string): number | null {
  const s = args.trim();
  const m = /^#?(\d+)$/.exec(s) || /(?:#|\/(?:issues|pull)\/)(\d+)\/?$/.exec(s);
  return m ? Number(m[1]) : null;
}

/** Typing filters the list: a number matches by prefix, words match the title or a label. */
export function matchItems(items: OpenItem[], args: string): OpenItem[] {
  const q = args.trim().toLowerCase();
  if (!q || (typedNumber(q) && !/^#?\d+$/.test(q))) return items;
  const num = /^#?(\d+)$/.exec(q);
  return items.filter((it) =>
    num ? String(it.number).startsWith(num[1]) : q.split(/\s+/).every((w) => it.title.toLowerCase().includes(w) || it.labels.some((l) => l.toLowerCase().includes(w))),
  );
}

/** The registered repo an issue/PR URL or `owner/repo#N` in the text names, else null. */
export function repoFromText(repos: Pick<Repo, 'slug'>[], text: string): string | null {
  const m = /(?:github\.com\/|(?:^|\s))([\w.-]+\/[\w.-]+)(?:\/(?:issues|pull)\/\d+|#\d+)/.exec(text);
  const hit = m && repos.find((r) => r.slug.toLowerCase() === m[1].toLowerCase());
  return hit ? hit.slug : null;
}

/** pr-grind's `issue` field: the PR number from a bare number or a /pull/N URL. */
export function grindPr(args: string): number | null {
  const s = args.trim();
  const m = /^#?(\d+)$/.exec(s) || /^https?:\/\/[^/\s]+\/[^/\s]+\/[^/\s]+\/pull\/(\d+)\/?$/.exec(s);
  const n = m ? Number(m[1]) : 0;
  return n > 0 ? n : null;
}

/**
 * The argument after switching command. Same kind carries over: free text as typed; an issue or PR
 * number rewritten in the new command's form (a reference to another repo is kept as typed); other
 * kinds would not parse in the new command, so they are cleared.
 */
export function switchArgs(from: { id: string; arg: ArgKind }, to: { id: string; arg: ArgKind }, args: string, slug: string, items: OpenItem[]): string {
  if (from.arg !== to.arg) return '';
  if (from.arg === 'text' || from.arg === 'issues') return args;
  if (from.arg !== 'issue' && from.arg !== 'pr') return '';
  const n = typedNumber(args);
  if (n == null) return args;
  const named = /(?:\/\/[^/\s]+\/|^)([\w.-]+\/[\w.-]+)(?:\/(?:issues|pull)\/\d+|#\d+)\/?$/.exec(args.trim());
  if (named && named[1].toLowerCase() !== slug.toLowerCase()) return args;
  return pickValue(to.id, items.find((it) => it.number === n) ?? { number: n, url: null });
}

// ---- accounts -------------------------------------------------------------------------------------
/** Reset time (epoch s) of the account with this label when it is rate limited, else null. */
export function limitedUntil(cmds: { label: string; cmd: string }[] | undefined, label: string, limits: Record<string, Limit> | undefined, nowSec = Date.now() / 1000): number | null {
  const c = (cmds ?? []).find((x) => x.label === label);
  const until = c && limits?.[c.cmd]?.limited_until;
  return until && until > nowSec ? until : null;
}

// ---- notes-vault folder ---------------------------------------------------------------------------
export interface FolderPick {
  project: string;
  feature: string;
  touched?: boolean;
}
const STOP = new Set('the and for with from that this into have will should would could about when what which there their them they then than your our new add make build want need idea app feature page using also just like more some each only over under'.split(' '));
export const words = (s: string) => [...new Set(s.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length > 2 && !STOP.has(w)))];

/** Existing folders ranked by how many of the text's words their project and feature names share. */
export function keywordSuggest(folders: { project: string; feature: string | null }[], text: string, n = 3) {
  const want = words(text);
  if (!want.length) return [];
  const near = (a: string, b: string) => a.startsWith(b) && a.length - b.length <= 2;
  const hits = (names: string[]) => want.filter((w) => names.some((x) => x === w || near(x, w) || near(w, x))).length;
  return folders
    .map((f) => {
      const feat = hits(words(f.feature || ''));
      if (f.feature && !feat) return { project: f.project, feature: f.feature, score: 0 };
      return { project: f.project, feature: f.feature, score: 2 * hits(words(f.project)) + feat + (feat ? 0.5 : 0) };
    })
    .filter((s) => s.score >= 1)
    .sort((a, b) => b.score - a.score)
    .slice(0, n);
}

/** `05-Work/<Project>[/<Feature>]` for a choice, or null when no project is named. */
export function folderOf({ project, feature }: Partial<FolderPick> = {}): string | null {
  const p = String(project || '').trim().replace(/[/\\]/g, ' ');
  const f = String(feature || '').trim().replace(/[/\\]/g, ' ');
  if (!p || p.startsWith('.') || f.startsWith('.')) return null;
  return f ? `05-Work/${p}/${f}` : `05-Work/${p}`;
}

// ---- request bodies -------------------------------------------------------------------------------
export type WhereSel = { kind: 'repo'; slug: string } | { kind: 'path'; path: string } | { kind: 'vault' };

/** The repo, or the no-repo fields when "No repo yet" is chosen. */
export function whereBody(w: WhereSel, folder: string | null): SessionStartBody {
  if (w.kind === 'vault') return { repo: '', no_repo: true, ...(folder ? { vault_folder: folder } : {}) };
  return { repo: (w.kind === 'repo' ? w.slug : w.path).trim() };
}

/** The POST /api/sessions body: {repo|no_repo+vault_folder, command, args} or {text}, plus issue, claude_cmd, batch, peer_review. */
export function startBody(o: {
  where: WhereSel;
  folder: string | null;
  command: string;
  args: string;
  lenses: string[];
  account?: string;
  batch?: string;
  model?: string | null;
  effort?: string | null;
}): SessionStartBody {
  const body: SessionStartBody = o.command === 'custom' ? { text: o.args.trim() } : { command: o.command, args: o.args.trim() };
  if (o.lenses.length) body.peer_review = o.lenses; // the server appends --review <lenses>, or asks a custom prompt to run it
  if (o.command === 'pr-grind') {
    const pr = grindPr(o.args);
    if (pr) body.issue = pr;
  }
  if (o.batch) body.batch = o.batch;
  if (o.model) body.model = o.model;
  if (o.effort) body.effort = o.effort;
  const out = { ...whereBody(o.where, o.folder), ...body };
  return o.account ? { ...out, claude_cmd: o.account } : out;
}
