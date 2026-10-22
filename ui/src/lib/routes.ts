// Route table helpers: typed hrefs and the legacy redirects (FR-2). All paths are HashRouter paths.

export const routes = {
  inbox: '/inbox',
  features: '/features',
  feature: (slug: string, tab?: string) => `/features/${encodeURIComponent(slug)}${tab ? `/${tab}` : ''}`,
  board: '/board',
  activity: '/activity',
  dispatches: '/dispatches',
  /** Dispatches with the New dispatch dialog open on this epic (owner/repo#n). */
  newDispatch: (epic: string) => `/dispatches?new=${encodeURIComponent(epic)}`,
  dispatch: (id: string) => `/dispatches/${encodeURIComponent(id)}`,
  session: (id: string) => `/sessions/${encodeURIComponent(id)}`,
  settings: (section?: string) => `/settings${section ? `/${section}` : ''}`,
  onboarding: '/onboarding',
} as const;

export interface Redirect {
  to: string; // path + search
  start?: boolean; // open the Start dialog after redirecting (#/new)
}

/**
 * Old hash routes (the Preact UI and its ntfy links) -> new ones; null when `pathname` is not a legacy route.
 * `search` is the query string of the old route (with its leading "?"), kept so ?repo= survives.
 */
export function legacyRedirect(pathname: string, search = ''): Redirect | null {
  const seg = pathname.replace(/\/+$/, '').split('/').slice(1).map(decodeURIComponent);
  const [a, b, c, d] = seg;
  const keep = (p: string) => ({ to: p + search });
  if (seg.length === 0) return keep(routes.inbox); // "#/" and "" open the Inbox
  if (a === 'planning' && !b) return keep(routes.features);
  if (a === 'delivery' && !b) return keep(routes.board);
  if (a === 'sessions' && !b) return keep(routes.activity); // the old Sessions list
  if ((a === 'session' || a === 'answer' || a === 'dispatch') && b && !c) return keep(routes.session(b));
  if (a === 'new' && !b) return { ...keep(routes.inbox), start: true };
  if (a === 'run' && b && c && d) {
    const sp = new URLSearchParams(search);
    sp.set('repo', `${b}/${c}`);
    return { to: `${routes.board}?${sp.toString().replace(/%2F/gi, '/')}` }; // ntfy "issue" link
  }
  return null;
}
