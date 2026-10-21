import { useAfkStop, useInbox, useOffline, useSessions } from '../api/hooks';
import { Banner, Button, toast } from '../components';
import { clockText } from '../lib/format';

export function OfflineBanner() {
  const offline = useOffline();
  if (!offline) return null;
  return (
    <Banner tone="bad" icon="wifi" top>
      <p><b>Can't reach the aiw server.</b> Retrying every 3 seconds. Actions are paused; what you see may be out of date.</p>
    </Banner>
  );
}

export function AwayBanner() {
  const afk = useSessions().data?.afk;
  const stop = useAfkStop();
  if (!afk?.active || !afk.until) return null;
  return (
    <Banner tone="away" icon="moon" top action={<Button sm onClick={() => stop.mutate(undefined, { onSuccess: () => toast('Welcome back. See what happened in your Inbox.') })}>I'm back</Button>}>
      <p><b>Away until {clockText(afk.until)}.</b> Claude answers questions that have a recommended option and retries failures. The rest waits in your Inbox.</p>
    </Banner>
  );
}

/** For Features and Board (FR-30): shown when gh is signed out. Renders nothing while gh is fine or unknown. */
export function GhBanner() {
  const fromSessions = useSessions().data?.gh;
  const fromInbox = useInbox().data?.gh;
  const gh = fromSessions ?? fromInbox;
  if (!gh || gh.ok) return null;
  return (
    <Banner tone="bad" icon="github">
      <p><b>GitHub CLI is not signed in.</b> Boards, issue actions and merges are paused until gh can reach GitHub.</p>
      <p className="muted">Run <code>gh auth login</code> in a terminal, then reload.</p>
    </Banner>
  );
}
