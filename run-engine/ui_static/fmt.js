// Small display formatters shared by the views.

const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

// "Today 13:48", "Yesterday 17:40", "Oct 5 09:15"; "—" for a missing or unparseable time.
export function formatWhen(iso, now = new Date()) {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return '—';
  const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86400000);
  if (days === 0) return `Today ${hm}`;
  if (days === 1) return `Yesterday ${hm}`;
  const date = d.toLocaleDateString([], d.getFullYear() === now.getFullYear() ? { month: 'short', day: 'numeric' } : { year: 'numeric', month: 'short', day: 'numeric' });
  return `${date} ${hm}`;
}

// Last path segment of a repo path or owner/repo slug.
export const shortRepo = (repo) => String(repo || '').replace(/\/+$/, '').split('/').pop() || '—';

// "in 1h 12m", "in 5m", "now" for an epoch-seconds reset time.
export function untilText(epochSec, nowMs = Date.now()) {
  const m = Math.ceil((epochSec * 1000 - nowMs) / 60000);
  if (!(m > 0)) return 'now';
  return m >= 60 ? `in ${Math.floor(m / 60)}h ${m % 60}m` : `in ${m}m`;
}

// Local "HH:MM" of an epoch-seconds time.
export const clockText = (epochSec) => new Date(epochSec * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });

// Label for a run's review-grind state ({state, round} or null).
export function grindLabel(g) {
  if (!g) return '';
  const r = g.round ? ` · round ${g.round}` : '';
  return { queued: 'grind queued', running: `grinding${r}`, idle: `grind idle${r}`, paused: `grind paused${r}`, done: 'grind done' }[g.state] || '';
}

// One-line gist of a tool call: its most telling argument, capped.
export function toolSummary(e, max = 110) {
  const input = e && e.input;
  let s = '';
  if (input && typeof input === 'object') {
    const key = ['command', 'file_path', 'path', 'pattern', 'url', 'description', 'prompt', 'skill'].find((k) => typeof input[k] === 'string' && input[k]);
    s = key ? input[key] : JSON.stringify(input);
  } else if (input !== undefined && input !== null) s = String(input);
  s = s.replace(/\s+/g, ' ').trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

// Short name for a session in lists: grind sessions carry long instruction text as their command.
export const sessionLabel = (command) => (/^\/(?:[\w-]+:)?pr-grind\b/.test(command) ? 'pr-grind round' : String(command).startsWith('Start the review grind') ? 'pr-grind start' : String(command));

// Splits plain text into strings and { href } parts for http(s) URLs; trailing punctuation stays outside the link.
export function linkParts(text) {
  const s = String(text ?? '');
  const out = [];
  let last = 0;
  for (const m of s.matchAll(/https?:\/\/[^\s<>"'`]+/g)) {
    const href = m[0].replace(/[.,;:!?)\]}]+$/, '');
    out.push(s.slice(last, m.index), { href });
    last = m.index + href.length;
  }
  out.push(s.slice(last));
  return out;
}
