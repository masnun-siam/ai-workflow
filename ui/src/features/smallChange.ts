import { useSessions } from '../api/hooks';
import type { SessionStatus } from '../api/types';
import { sessionInRepo } from '../lib/format';
import { isLive } from '../lib/vocab';
import { useRepo } from '../shell/useRepo';

export const SMALL_CHANGE_MARKER = 'Small change (no PRD):';

/** Appended to every small-change arg: makes /create-tasks skip the PRD question and chain /refine-issues. */
export const SMALL_CHANGE_NOTE =
  ' Instructions: this change has no PRD and does not need one. Follow "A finding from other work" and go on without a PRD: do not search for one and do not ask which PRD it belongs to; the issue gets no prd-<slug> label and no epic parent. Still ask me to confirm before creating the issue. Once it is created, run /ai-workflow:refine-issues on its number in this same session instead of stopping at the hand-off; there is no PRD to read or update. My yes to create the issue also approves refining it, so do not ask a second time before writing the refined body. If I decline, stop and file nothing.';

export const smallChangeArg = (text: string) => `${SMALL_CHANGE_MARKER} ${text.trim().replace(/\s+/g, ' ')}${SMALL_CHANGE_NOTE}`;

export const SMALL_CHANGE_LOCK = 'A small change is being filed and refined. Wait for it to finish.';

/** The text typed in the describe box, from a small-change /create-tasks command; null for any other command. */
export function smallChangeText(command: string): string | null {
  const m = new RegExp(`^/(?:[\\w-]+:)?create-tasks\\s+${SMALL_CHANGE_MARKER.replace(/[()]/g, '\\$&')}\\s*(.*)$`, 's').exec(command);
  if (!m) return null;
  return (m[1].endsWith(SMALL_CHANGE_NOTE) ? m[1].slice(0, -SMALL_CHANGE_NOTE.length) : m[1]).trim();
}

export type PendingChange = { id: string; text: string; status: SessionStatus };

/** Live small-change create sessions of this repo, newest first. */
export function useSmallChangeSessions(repo: string): PendingChange[] {
  const sessions = useSessions().data?.sessions ?? [];
  const path = useRepo().current?.path;
  return sessions
    .flatMap((s) => {
      const text = smallChangeText(s.command);
      return text !== null && isLive(s.outcome) && sessionInRepo(s, repo, path) ? [{ s, text }] : [];
    })
    .sort((a, b) => String(b.s.started_at).localeCompare(String(a.s.started_at)))
    .map(({ s, text }) => ({ id: s.id, text, status: s.outcome }));
}
