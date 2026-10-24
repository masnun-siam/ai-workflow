// Shared start helpers for Board, Features and the panels: one place that turns a start into "open its session",
// a herdr toast, or (409) a toast linking to the session that already runs.
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../api/client';
import { api } from '../api/endpoints';
import { useApiMutation, useSessions } from '../api/hooks';
import type { BoardStartBody, SessionStartBody } from '../api/types';
import { toast } from '../components';
import { parseSkill, sessionSlug } from '../lib/format';
import { routes } from '../lib/routes';
import { isLive } from '../lib/vocab';
import { useRepo } from '../shell/useRepo';

const SESSION_WRITES = [['sessions'], ['inbox'], ['session']];
const ALL_WRITES = [...SESSION_WRITES, ['planning'], ['delivery']];

export function useStarter() {
  const navigate = useNavigate();
  const { link } = useRepo();
  const board = useApiMutation(api.startBoard, ALL_WRITES, { quiet: true });
  const sess = useApiMutation(api.startSession, ALL_WRITES, { quiet: true });

  const fail = (e: unknown) => {
    const err = e instanceof ApiError ? e : null;
    const dup = err?.duplicate;
    if (dup?.id) toast(err!.message, { action: { label: 'Open session', onClick: () => navigate(link(routes.session(dup.id!))) } });
    else toast.error(e instanceof Error ? e.message : 'Something went wrong');
  };
  const opened = (id?: string | null, nav = true) => {
    if (id && nav) navigate(link(routes.session(id)));
    return id ?? null;
  };

  return {
    pending: board.isPending || sess.isPending,
    /** POST /api/start. Resolves to the new session id (null on failure). */
    async startBoard(body: BoardStartBody, o: { nav?: boolean } = {}): Promise<string | null> {
      try {
        const r = await board.mutateAsync(body);
        return opened(r.session, o.nav !== false);
      } catch (e) {
        fail(e);
        return null;
      }
    },
    /** POST /api/sessions. */
    async startSession(body: SessionStartBody, o: { nav?: boolean } = {}): Promise<string | null> {
      try {
        const r = await sess.mutateAsync(body);
        return opened(r.id, o.nav !== false);
      } catch (e) {
        fail(e);
        return null;
      }
    },
  };
}

/** {issue number: session id} of the live /refine-issues sessions for a repo, so Refine can show it is running instead of starting another. */
export function useRefining(repo: string): Map<number, string> {
  const sessions = useSessions().data?.sessions ?? [];
  const out = new Map<number, string>();
  for (const s of sessions) {
    const p = parseSkill(s.command);
    if (p?.skill !== 'refine-issues' || !isLive(s.outcome) || sessionSlug(s).toLowerCase() !== repo.toLowerCase()) continue;
    for (const n of p.rest.split('\n')[0].match(/\d+/g) ?? []) out.set(Number(n), s.id);
  }
  return out;
}
