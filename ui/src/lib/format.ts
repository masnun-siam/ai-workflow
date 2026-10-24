// Display formatters shared by the views (ported from the old UI, typed).
import type { Session, SessionLink } from '../api/types';

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

/** "Today 13:48", "Yesterday 17:40", "Oct 5 09:15"; "—" for a missing or unparseable time. */
export function formatWhen(iso: string | number | null | undefined, now = new Date()): string {
  const d = new Date(iso ?? NaN);
  if (!iso || Number.isNaN(d.getTime())) return '—';
  const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86400000);
  if (days === 0) return `Today ${hm}`;
  if (days === 1) return `Yesterday ${hm}`;
  const date = d.toLocaleDateString(
    [],
    d.getFullYear() === now.getFullYear() ? { month: 'short', day: 'numeric' } : { year: 'numeric', month: 'short', day: 'numeric' },
  );
  return `${date} ${hm}`;
}

/** Last path segment of a repo path or owner/repo slug. */
export const shortRepo = (repo: string | null | undefined) => String(repo || '').replace(/\/+$/, '').split('/').pop() || '—';
/** shortRepo, or the full owner/repo when another slug in `all` has the same short name. */
export const repoLabel = (slug: string, all: string[]) => (all.filter((s) => shortRepo(s) === shortRepo(slug)).length > 1 ? slug : shortRepo(slug));

/** "in 1h 12m", "in 5m", "now" for an epoch-seconds reset time. */
export function untilText(epochSec: number, nowMs = Date.now()): string {
  const m = Math.ceil((epochSec * 1000 - nowMs) / 60000);
  if (!(m > 0)) return 'now';
  return m >= 60 ? `in ${Math.floor(m / 60)}h ${m % 60}m` : `in ${m}m`;
}

/** Local "HH:MM" of an epoch-seconds time. */
export const clockText = (epochSec: number) =>
  new Date(epochSec * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });

/** "now", "12m", "3h", "4d" since an epoch-seconds time. */
export function ago(epochSec: number | null | undefined, nowMs = Date.now()): string {
  if (typeof epochSec !== 'number' || !Number.isFinite(epochSec)) return '';
  const s = Math.max(0, nowMs / 1000 - epochSec);
  return s < 60 ? 'now' : s < 3600 ? `${Math.floor(s / 60)}m` : s < 86400 ? `${Math.floor(s / 3600)}h` : `${Math.floor(s / 86400)}d`;
}

/** "ago" for an ISO time. */
export const agoIso = (iso: string | null | undefined, nowMs = Date.now()) => (iso ? ago(Date.parse(iso) / 1000, nowMs) : '');

/** Run duration "21 min", "1 h 5 min", "40 s". */
export function duration(startIso: string | null | undefined, endIso?: string | null, nowMs = Date.now()): string {
  const a = Date.parse(startIso ?? '');
  if (Number.isNaN(a)) return '—';
  const b = endIso ? Date.parse(endIso) : nowMs;
  const s = Math.max(0, Math.round((b - a) / 1000));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

export const money = (n: number | null | undefined) => (typeof n === 'number' ? `$${n.toFixed(2)}` : '—');

export function fmtTokens(n: number): string {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '';
  return n < 1000 ? String(n) : n < 1e6 ? `${(n / 1000).toFixed(n < 1e4 ? 1 : 0)}k` : `${(n / 1e6).toFixed(n < 1e7 ? 2 : 1)}M`;
}
export const tokensText = (t: Session['tokens']) =>
  t && typeof t.input === 'number' && typeof t.output === 'number' ? `${fmtTokens(t.input + t.output)} tok` : '';

/** Label for a grind: "grinding · round 2", "grind paused · round 3". */
export function grindLabel(g: { state: string; round?: number } | null | undefined): string {
  if (!g) return '';
  const r = g.round ? ` · round ${g.round}` : '';
  const m: Record<string, string> = { queued: 'grind queued', running: `grinding${r}`, idle: `grind idle${r}`, paused: `grind paused${r}`, done: 'grind done' };
  return m[g.state] || '';
}

/** One-line gist of a tool call: its most telling argument, capped. */
export function toolSummary(input: unknown, max = 110): string {
  let s = '';
  if (input && typeof input === 'object') {
    const o = input as Record<string, unknown>;
    const key = ['command', 'file_path', 'path', 'pattern', 'url', 'description', 'prompt', 'skill'].find(
      (k) => typeof o[k] === 'string' && o[k],
    );
    s = key ? (o[key] as string) : JSON.stringify(input);
  } else if (input !== undefined && input !== null) s = String(input);
  s = s.replace(/\s+/g, ' ').trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

/** Short name for a session in lists: grind sessions carry long instruction text as their command. */
export const sessionLabel = (command: string) =>
  parseSkill(command)?.skill === 'pr-grind' ? 'pr-grind round' : String(command).startsWith('Start the review grind') ? 'pr-grind start' : String(command);

/** A session's skill and argument from its command, in either spelling ("/implement-issue 801" or "/ai-workflow:implement-issue 801"); null for free text. */
export function parseSkill(command: string): { skill: string; rest: string } | null {
  const m = /^\/(?:[\w-]+:)?([\w-]+)(?:\s+([\s\S]*))?$/.exec(String(command ?? ''));
  return m ? { skill: m[1], rest: (m[2] ?? '').trim() } : null;
}

/** The skill name of a session's command: "/ai-workflow:implement-issue 801" -> "implement-issue". */
export const skillOf = (command: string) => parseSkill(command)?.skill ?? '';

/** A command without its plugin prefix and slash: "/ai-workflow:implement-issue 801" -> "implement-issue 801"; free text as is. */
export const commandText = (command: string) => {
  const p = parseSkill(command);
  return p ? `${p.skill}${p.rest ? ` ${p.rest}` : ''}` : String(command ?? '').trim();
};

/** Splits text into strings and {href} parts for http(s) URLs; trailing punctuation stays outside the link. */
export function linkParts(text: unknown): (string | { href: string })[] {
  const s = String(text ?? '');
  const out: (string | { href: string })[] = [];
  let last = 0;
  for (const m of s.matchAll(/https?:\/\/[^\s<>"'`]+/g)) {
    const href = m[0].replace(/[.,;:!?)\]}]+$/, '');
    out.push(s.slice(last, m.index), { href });
    last = (m.index ?? 0) + href.length;
  }
  out.push(s.slice(last));
  return out;
}

/** True when a session belongs to `repo` (owner/name): by slug when it has one, else by the checkout path `repo` of the current repo. */
export function sessionInRepo(s: Pick<Session, 'link' | 'repo' | 'slug'>, repo: string, path?: string): boolean {
  const slug = sessionSlug(s);
  return slug ? slug.toLowerCase() === repo.toLowerCase() : !!path && s.repo === path;
}

/** owner/name of a session, from its link or a bare slug in `repo`; '' when unknown (checkout path only). */
export function sessionSlug(s: Pick<Session, 'link' | 'repo' | 'slug'>): string {
  if (s.slug) return s.slug;
  const l = s.link as SessionLink | string | null;
  if (l && typeof l === 'object' && l.owner && l.repo) return `${l.owner}/${l.repo}`;
  const m = typeof l === 'string' ? /github\.com\/([^/]+\/[^/]+)/.exec(l) : null;
  if (m) return m[1];
  return s.repo && !s.repo.startsWith('/') ? s.repo : '';
}
