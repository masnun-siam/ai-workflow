// "Continue in terminal": the resume command, copied to the clipboard (shown in a toast if copying is blocked).
import { useCallback } from 'react';
import { api } from '../api/endpoints';
import type { Session } from '../api/types';
import { toast } from '../components';

const q = (s: string) => `'${s.replace(/'/g, "'\\''")}'`;
export const resumeCommand = (s: Pick<Session, 'resume_command' | 'repo_path' | 'session_id'>): string | null =>
  s.resume_command || (s.session_id ? `cd ${q(s.repo_path || '.')} && claude --resume ${q(s.session_id)}` : null);

export async function copyCommand(cmd: string | null) {
  if (!cmd) return toast.error('This session has no Claude conversation to resume yet.');
  try {
    await navigator.clipboard.writeText(cmd);
    toast('Resume command copied. Paste it in a terminal.');
  } catch {
    toast.error(`Could not copy. Run it yourself: ${cmd}`, { ms: 20000 });
  }
}

/** `const terminal = useTerminal(); terminal(sessionId)` fetches the session and copies its resume command. */
export function useTerminal() {
  return useCallback(async (id: string) => {
    try {
      await copyCommand(resumeCommand(await api.session(id)));
    } catch {
      toast.error('Could not load the session.');
    }
  }, []);
}
