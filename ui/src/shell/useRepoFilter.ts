import { useCallback, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useRepos } from '../api/hooks';
import { withParam } from '../lib/repo';

/**
 * The page's repo filter (FR-1): `?only=<owner/repo>`. `only` is the registered slug it names, else ''.
 * Independent of the switcher: it never reads or sets ?repo= or aiw.repo.
 */
export function useRepoFilter() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const q = useRepos();
  const raw = new URLSearchParams(search).get('only') || '';
  const match = q.data?.repos.find((r) => r.slug.toLowerCase() === raw.toLowerCase());
  const only = q.isSuccess ? (match?.slug ?? '') : raw;
  useEffect(() => {
    if (q.isSuccess && raw && !match) navigate({ pathname, search: withParam(search, 'only', '') }, { replace: true });
  }, [q.isSuccess, raw, match, navigate, pathname, search]);
  const setOnly = useCallback(
    (slug: string) => navigate({ pathname, search: withParam(search, 'only', slug) }),
    [navigate, pathname, search],
  );
  return { only, setOnly };
}
