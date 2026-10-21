import { useCallback, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useRepos } from '../api/hooks';
import { pickRepo, rememberRepo, storedRepo, withRepoParam } from '../lib/repo';
import { routes } from '../lib/routes';

/**
 * The current repo (FR-3): ?repo= in the URL, else the remembered one, else the first registered.
 * `repo` is '' until /api/repos has loaded or when none is registered (`loaded` tells which).
 * `link(path)` builds an in-app path that carries the repo; `setRepo` switches it on the current page.
 */
export function useRepo() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const q = useRepos();
  const repos = q.data?.repos ?? [];
  const fromUrl = new URLSearchParams(search).get('repo') || '';
  const repo = pickRepo(search, repos.map((r) => r.slug), storedRepo());
  useEffect(() => {
    if (fromUrl) rememberRepo(fromUrl);
  }, [fromUrl]);
  const setRepo = useCallback(
    (slug: string) => {
      rememberRepo(slug);
      const dest = pathname.startsWith(routes.features + '/') ? routes.features : pathname;
      navigate({ pathname: dest, search: withRepoParam(search, slug) });
    },
    [navigate, pathname, search],
  );
  const link = useCallback((path: string) => (repo ? `${path}${path.includes('?') ? '&' : '?'}repo=${repo}` : path), [repo]);
  return { repo, repos, loaded: q.isSuccess, setRepo, link, current: repos.find((r) => r.slug === repo) };
}
