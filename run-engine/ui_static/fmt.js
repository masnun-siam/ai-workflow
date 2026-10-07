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
