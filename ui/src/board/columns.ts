import type { FeatureIssue } from '../lib/features';
import { BOARD_COLUMNS, boardColumn, type BoardColumnId } from '../lib/vocab';

/** An issue is in exactly one column (FR-18). Blocked issues are listed last in Ready; the rest keep server order. */
export function placeCards<T extends Pick<FeatureIssue, 'column' | 'blocked_by'>>(cards: T[]): Record<BoardColumnId, T[]> {
  const out = Object.fromEntries(BOARD_COLUMNS.map((c) => [c.id, [] as T[]])) as Record<BoardColumnId, T[]>;
  for (const c of cards) out[boardColumn(c)].push(c);
  out.ready.sort((a, b) => Number(a.blocked_by.length > 0) - Number(b.blocked_by.length > 0));
  return out;
}

/** True when a card needs the user: a question waiting or a paused grind. */
export const needsYou = (c: Pick<FeatureIssue, 'session' | 'grind'>) => c.session?.status === 'waiting' || c.grind?.state === 'paused';
