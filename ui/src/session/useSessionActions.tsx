// FR-21: Stop, Retry/Resume, Rerun, Continue in terminal, from the Activity table and the session page.
import { useNavigate } from 'react-router-dom';
import { useRerun, useResume, useStop } from '../api/hooks';
import type { ApiError } from '../api/client';
import type { Session } from '../api/types';
import { Button, useConfirm, useToast, type MenuEntry } from '../components';
import { routes } from '../lib/routes';
import { isLive } from '../lib/vocab';
import { useTerminal } from './terminal';

/** One toast for a failed resume/rerun: a 409 duplicate offers "Open it", anything else shows the server's message. */
export function useStartError() {
  const nav = useNavigate();
  const toast = useToast();
  return (e: ApiError) => {
    const id = e.duplicate?.id;
    if (id) toast.error('That is already running.', { action: { label: 'Open it', onClick: () => nav(routes.session(id)) } });
    else toast.error(e.message);
  };
}

export function useSessionActions() {
  const nav = useNavigate();
  const confirm = useConfirm();
  const terminal = useTerminal();
  const stop = useStop();
  const resume = useResume();
  const rerun = useRerun();
  const dup = useStartError();
  return {
    terminal,
    stop: async (id: string) => {
      if (await confirm({ title: 'Stop this session?', body: 'Claude stops now. You can resume it later.', okLabel: 'Stop session', danger: true })) stop.mutate(id);
    },
    resume: (id: string, claude_cmd?: string) => resume.mutate({ id, claude_cmd }, { onError: dup }),
    rerun: (id: string) => rerun.mutate(id, { onSuccess: (s) => nav(routes.session(s.id)), onError: dup }),
    busy: stop.isPending || resume.isPending || rerun.isPending,
  };
}
export type SessionActionsApi = ReturnType<typeof useSessionActions>;

/** The primary button for a session's state, and the ⋯ menu entries. */
export function sessionButtons(s: Session, a: SessionActionsApi, go: (path: string) => void, sm = true) {
  const live = isLive(s.outcome);
  let main: React.ReactNode = null;
  if (s.outcome === 'waiting') main = <Button sm={sm} variant="you" onClick={() => go(routes.session(s.id))}>Answer</Button>;
  else if (s.outcome === 'failed') main = <Button sm={sm} disabled={a.busy} onClick={() => a.resume(s.id)}>Retry</Button>;
  else if (s.outcome === 'stopped') main = <Button sm={sm} disabled={a.busy} onClick={() => a.resume(s.id)}>Resume</Button>;
  const entries: MenuEntry[] = [
    live ? { label: 'Stop session', icon: 'stop', danger: true, onSelect: () => void a.stop(s.id) } : { label: 'Run again with the same input', icon: 'refresh', onSelect: () => a.rerun(s.id) },
    { label: 'Copy terminal resume command', icon: 'terminal', onSelect: () => void a.terminal(s.id) },
  ];
  return { main, entries };
}
