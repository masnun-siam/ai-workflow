import * as PO from '@radix-ui/react-popover';
import { useRef, useState } from 'react';
import { useCreateShare, useDeleteApproval, useStopShare } from '../api/hooks';
import { Button, toast, useConfirm } from '../components';
import { NOT_SHAREABLE, approvalsLabel, commentsLabel, isShareable, removeBody, shareBody, stopBody } from '../lib/shares';
import { useOwnShare } from './useOwnShare';

/** Share button for the PRD tab: confirm and create a link, then the popover with the link, approvals and Stop. */
export function SharePopover({ status, repo, path }: { status: string; repo: string; path: string }) {
  const { summary, share, live } = useOwnShare(repo, path);
  const create = useCreateShare();
  const stop = useStopShare();
  const delApproval = useDeleteApproval();
  const confirm = useConfirm();
  const [open, setOpen] = useState(false);
  const link = useRef<HTMLInputElement>(null);
  const days = useRef(0);
  const asking = useRef(false); // a second click while the confirm is open must not open another
  const approvals = share.data?.approvals ?? [];
  const n = approvals.length;
  const ok = isShareable(status);

  const doShare = async () => {
    if (create.isPending || asking.current) return;
    asking.current = true;
    days.current = 0;
    const yes = await confirm({
      title: 'Share this PRD publicly?',
      okLabel: 'Share',
      body: (
        <>
          <p>{shareBody(summary?.state === 'ended' ? n : 0)}</p>
          <label className="row">
            Expires{' '}
            <select className="f" defaultValue="0" onChange={(e) => { days.current = Number(e.target.value); }}>
              <option value="0">Never</option>
              <option value="1">In 1 day</option>
              <option value="7">In 7 days</option>
              <option value="30">In 30 days</option>
            </select>
          </label>
        </>
      ),
    });
    asking.current = false;
    if (!yes) return;
    create.reset();
    create.mutate({ repo, path, expiresInDays: days.current || undefined }, { onSettled: () => setOpen(true) });
  };
  const doStop = async () => {
    if (!summary || !(await confirm({ title: 'Stop sharing?', okLabel: 'Stop', danger: true, body: <p>{stopBody(n)}</p> }))) return;
    stop.mutate(summary.id);
  };
  const doRemove = async (id: string, name: string) => {
    if (!summary || !(await confirm({ title: 'Remove approval?', okLabel: 'Remove', danger: true, body: <p>{removeBody(name)}</p> }))) return;
    delApproval.mutate({ id: summary.id, aid: id });
  };
  const copy = async () => {
    if (!summary?.url) return;
    try {
      await navigator.clipboard.writeText(summary.url);
      toast('Link copied');
    } catch {
      link.current?.select();
      toast.error('Could not copy. The link is selected: copy it yourself.');
    }
  };

  return (
    <PO.Root open={open} onOpenChange={setOpen}>
      <PO.Trigger asChild>
        <Button
          disabled={!ok || create.isPending}
          title={ok ? undefined : NOT_SHAREABLE}
          onClick={(e) => {
            if (!live) { e.preventDefault(); void doShare(); }
          }}
        >
          {create.isPending ? 'Sharing…' : 'Share'}
        </Button>
      </PO.Trigger>
      <PO.Portal>
        <PO.Content className="pop-c" align="end" sideOffset={6} collisionPadding={8} style={{ padding: 14, width: 360 }}>
          <div className="stack">
            {create.error ? <p role="alert">{create.error.message}</p> : null}
            {live && summary?.url ? (
              <>
                <div className="row">
                  <input ref={link} className="f grow mono" readOnly aria-label="Share link" value={summary.url} onFocus={(e) => e.currentTarget.select()} />
                  <Button sm onClick={copy}>Copy</Button>
                </div>
                {!summary.reachable ? <p className="muted">Not reachable right now. aiw will retry at the next start or share action.</p> : null}
                <p>{commentsLabel(summary.comments)}</p>
                <div>
                  <p>{approvalsLabel(n)}</p>
                  <ul>
                    {approvals.map((a) => (
                      <li key={a.id} className="row">
                        <span className="grow">{a.name}</span>
                        <Button sm variant="ghost" aria-label={`Remove ${a.name}'s approval`} onClick={() => doRemove(a.id, a.name)}>Remove</Button>
                      </li>
                    ))}
                  </ul>
                </div>
                <p className="muted">Ends when the PRD leaves Draft or In review</p>
                {summary.expires_at ? <p className="muted">Expires {new Date(summary.expires_at).toLocaleDateString()}</p> : null}
                <Button variant="danger" disabled={stop.isPending} onClick={doStop}>Stop</Button>
              </>
            ) : !create.error ? (
              <p className="muted">{summary ? (summary.end_reason === 'expired' ? 'This share has expired.' : 'This share has ended.') : 'Not shared.'}</p>
            ) : null}
          </div>
        </PO.Content>
      </PO.Portal>
    </PO.Root>
  );
}
