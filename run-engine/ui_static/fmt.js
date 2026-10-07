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
