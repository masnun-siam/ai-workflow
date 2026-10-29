import { useShare, useShares } from '../api/hooks';

/** The author's share of one PRD: the list entry, its detail (approvals, threads) and whether it is live. */
export function useOwnShare(repo: string, path: string) {
  const summary = useShares().data?.find((s) => s.repo === repo && s.path === path);
  const share = useShare(summary?.id);
  return { summary, share, live: summary?.state === 'live' };
}
