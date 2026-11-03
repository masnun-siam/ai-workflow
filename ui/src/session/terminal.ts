// "Continue in terminal": the resume command, copied to the clipboard (shown in a toast if copying is blocked).
import { useCallback } from 'react';
import { api } from '../api/endpoints';
import type { Session } from '../api/types';
import { toast } from '../components';

/** The server builds the harness's own command; the UI never builds one. */
export const resumeCommand = (s: Pick<Session, 'resume_command'>): string | null => s.resume_command || null;

export async function copyCommand(cmd: string | null) {
  if (!cmd) return toast.error('This session has nothing to resume in a terminal yet.');
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
