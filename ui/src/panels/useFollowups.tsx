// The follow-ups after an issue is done (merged or closed as completed): continue its implement-issue
// session with "do the follow-ups" (close, clean up, log learnings), or start a new one when that session is gone.
// ponytail: "already sent" lives in this browser's localStorage; move it to the server if it must follow you across browsers.
import { useSyncExternalStore } from 'react';
import { usePrompt, useSessions, useStartSession } from '../api/hooks';
import { toast, useConfirm } from '../components';

const KEY = 'aiw.followups';
const read = (): string[] => {
  try { return JSON.parse(localStorage.getItem(KEY) ?? '[]'); } catch { return []; }
};
let sent = new Set(read());
const listeners = new Set<() => void>();
const markSent = (k: string) => {
  sent = new Set(sent).add(k);
  try { localStorage.setItem(KEY, JSON.stringify([...sent])); } catch { /* private mode: keep it in memory */ }
  listeners.forEach((l) => l());
};
const subscribe = (l: () => void) => { listeners.add(l); return () => listeners.delete(l); };

export function useFollowups(repo: string) {
  const all = useSyncExternalStore(subscribe, () => sent);
  const sessions = useSessions().data?.sessions ?? [];
  const prompt = usePrompt();
  const startSession = useStartSession();
  const confirm = useConfirm();

  const isSent = (issueN: number) => all.has(`${repo}#${issueN}`);
  /** `why` is how the issue got done, e.g. "PR #12 is merged" or "issue #7 is closed". */
  const offer = async (issueN: number, why: string) => {
    if (isSent(issueN) || !(await confirm({ title: `Do the follow-ups for #${issueN}?`, okLabel: 'Do follow-ups', cancelLabel: 'Not now', body: <p>Tells the issue's implement-issue session that {why} so it closes the issue, cleans up and logs learnings.</p> })))
      return;
    markSent(`${repo}#${issueN}`);
    const text = `${why}, do the follow-ups.`;
    const fresh = () => startSession.mutate({ repo, command: 'implement-issue', args: `${issueN} ${text}`, issue: issueN }, { onSuccess: () => toast(`Started follow-ups for #${issueN}`) });
    const re = new RegExp(`^/(?:[\\w-]+:)?implement-issue\\s+#?${issueN}(?:\\s|$)`);
    const prev = sessions
      .filter((s) => s.session_id && (!s.slug || s.slug === repo) && re.test(s.command))
      .sort((a, b) => b.started_at.localeCompare(a.started_at))[0];
    if (!prev) return fresh();
    prompt.mutate({ id: prev.id, text }, { onSuccess: () => toast(`Follow-ups sent to #${issueN}'s session`), onError: fresh });
  };
  return { offer, isSent };
}
