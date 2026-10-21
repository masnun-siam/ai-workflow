import type { PrCheck, PrConvItem } from '../api/types';

/** What to warn about before a merge: failing or running checks, and each reviewer's latest verdict. Never blocks. */
export function mergeWarnings(checks: PrCheck[] | null | undefined, conversation: PrConvItem[] | null | undefined): string[] {
  const w: string[] = [];
  const cs = checks ?? [];
  const bad = cs.filter((c) => c.bucket === 'red').length;
  const wait = cs.filter((c) => c.bucket === 'pending').length;
  if (bad) w.push(`${bad} check${bad === 1 ? '' : 's'} failing`);
  else if (wait) w.push(`${wait} check${wait === 1 ? '' : 's'} still running`);
  const latest: Record<string, string> = {};
  for (const c of conversation ?? []) if (c.kind === 'review' && c.verdict && ['APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'].includes(c.verdict)) latest[c.author] = c.verdict;
  const v = Object.values(latest);
  if (v.includes('CHANGES_REQUESTED')) w.push('changes requested');
  else if (!v.includes('APPROVED')) w.push('no approving review');
  return w;
}
