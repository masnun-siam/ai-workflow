import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useSendPreview, useSendShare } from '../api/hooks';
import type { SendResult, Share } from '../api/types';
import { Button, useConfirm } from '../components';
import { routes } from '../lib/routes';
import { useRepo } from '../shell/useRepo';

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** "Send open comments (n)": shows the exact prompt, then starts the PRD update session with the unsent threads. */
export function SendComments({ share, outdatedIds, refetch }: { share: Share; outdatedIds: string[]; refetch: () => void }) {
  const { link } = useRepo();
  const confirm = useConfirm();
  const preview = useSendPreview();
  const send = useSendShare();
  const [result, setResult] = useState<SendResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = preview.isPending || send.isPending;

  const fail = (e: unknown) => {
    setError(e instanceof Error ? e.message : String(e));
    if (e instanceof ApiError && e.status === 409) refetch();
  };

  const run = async () => {
    setError(null);
    setResult(null);
    try {
      const p = await preview.mutateAsync({ id: share.id, outdated: outdatedIds });
      const ok = await confirm({
        title: 'Send open comments to the PRD session?',
        okLabel: 'Send',
        wide: true,
        body: (
          <div className="stack">
            {p.busy.panel ? <p role="note">A peer review panel is running on this PRD</p> : null}
            {p.busy.sessions.length ? <p role="note">A PRD update session is running on this PRD</p> : null}
            {p.dropped > 0 ? <p role="note">{plural(p.dropped, 'older comment', 'older comments')} on this thread won't be sent</p> : null}
            <pre style={{ maxHeight: '50vh', overflow: 'auto', whiteSpace: 'pre-wrap' }}>{p.prompt}</pre>
          </div>
        ),
      });
      if (!ok) return;
      setResult(await send.mutateAsync({ id: share.id, outdated: outdatedIds }));
    } catch (e) {
      fail(e);
    }
  };

  return (
    <>
      <Button sm disabled={share.unsent === 0 || busy} onClick={run}>Send open comments ({share.unsent})</Button>
      {result ? (
        <p role="status" className="muted">
          Sent {plural(result.threads, 'thread', 'threads')} to <Link to={link(routes.session(result.session_id))}>the session</Link>.
          {result.remaining > 0 ? ` ${plural(result.remaining, 'thread is', 'threads are')} still unsent.` : ''}
          {result.dropped > 0 ? ` ${plural(result.dropped, 'older comment was', 'older comments were')} left out for good.` : ''}
        </p>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
    </>
  );
}
