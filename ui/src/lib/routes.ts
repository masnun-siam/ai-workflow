// Typed hrefs for the route table. All paths are HashRouter paths.

export const routes = {
  inbox: '/inbox',
  features: '/features',
  feature: (slug: string, tab?: string) => `/features/${encodeURIComponent(slug)}${tab ? `/${tab}` : ''}`,
  activity: '/activity',
  dispatches: '/dispatches',
  /** Dispatches with the New dispatch dialog open on this epic (owner/repo#n). */
  newDispatch: (epic: string) => `/dispatches?new=${encodeURIComponent(epic)}`,
  dispatch: (id: string) => `/dispatches/${encodeURIComponent(id)}`,
  session: (id: string) => `/sessions/${encodeURIComponent(id)}`,
  settings: (section?: string) => `/settings${section ? `/${section}` : ''}`,
  onboarding: '/onboarding',
} as const;
