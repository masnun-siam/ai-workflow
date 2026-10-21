// The current repo: `?repo=owner/name` in the URL wins (shared links), else one localStorage key.
// Legacy keys (aiw.boardRepo, aiw.lastRepo) are read once into the new key, then removed.
export const REPO_KEY = 'aiw.repo';
const LEGACY = ['aiw.boardRepo', 'aiw.lastRepo'];

type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
const store = (): Store | null => {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
};
const read = (s: Store | null, k: string) => {
  try {
    return s?.getItem(k) || '';
  } catch {
    return '';
  }
};

/** Move a legacy pick into aiw.repo (only when aiw.repo is empty), drop the legacy keys. Returns the stored repo. */
export function migrateRepoKey(s: Store | null = store()): string {
  if (!s) return '';
  let cur = read(s, REPO_KEY);
  try {
    if (!cur) {
      cur = LEGACY.map((k) => read(s, k)).find((v) => v && !v.startsWith('/')) ?? '';
      if (cur) s.setItem(REPO_KEY, cur);
    }
    for (const k of LEGACY) s.removeItem(k);
  } catch {
    /* storage blocked: the URL still carries the repo */
  }
  return cur;
}

export const storedRepo = (s: Store | null = store()) => read(s, REPO_KEY);
export function rememberRepo(repo: string, s: Store | null = store()) {
  try {
    if (repo) s?.setItem(REPO_KEY, repo);
  } catch {
    /* ignore */
  }
}

/** The repo for a location search string: the URL's, else the remembered one, if it is still registered. */
export function pickRepo(search: string, known: string[], remembered: string): string {
  const fromUrl = new URLSearchParams(search).get('repo') || '';
  if (fromUrl) return fromUrl;
  if (remembered && (known.length === 0 || known.includes(remembered))) return remembered;
  return known[0] ?? '';
}

/** `search` with ?repo= set (dropped for ''), keeping other params and a readable slash. */
export function withRepoParam(search: string, repo: string): string {
  const sp = new URLSearchParams(search);
  if (repo) sp.set('repo', repo);
  else sp.delete('repo');
  const s = sp.toString().replace(/%2F/gi, '/');
  return s ? `?${s}` : '';
}
