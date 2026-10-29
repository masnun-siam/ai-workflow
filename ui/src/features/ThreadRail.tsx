import { useState, type ReactNode } from 'react';
import { useDeleteComment, useDeleteShareRecord, useDeleteThread, useReplyThread, useResolveThread } from '../api/hooks';
import type { Share, ShareThread } from '../api/types';
import { Button, useConfirm } from '../components';
import type { Placements } from '../lib/anchor';
import { formatWhen } from '../lib/format';
import { MAX_REPLY, deleteCommentBody, deleteRecordBody, deleteThreadBody } from '../lib/shares';

const QUOTE_MAX = 120;
const isNew = (t: ShareThread, baseline: string | null) =>
  t.comments.some((c) => !c.by_owner && (baseline === null || Date.parse(c.at) > Date.parse(baseline)));

function ThreadCard({ share, t, placed, isNew: fresh, onJump }: { share: Share; t: ShareThread; placed: boolean; isNew: boolean; onJump: (id: string) => void }) {
  const confirm = useConfirm();
  const reply = useReplyThread();
  const resolve = useResolveThread();
  const delThread = useDeleteThread();
  const delComment = useDeleteComment();
  const [open, setOpen] = useState(!t.resolved);
  const [text, setText] = useState('');
  const quote = t.anchor.exact.length > QUOTE_MAX ? `${t.anchor.exact.slice(0, QUOTE_MAX)}…` : t.anchor.exact;
  const fieldId = `reply-${t.id}`;

  const removeThread = async () => {
    if (await confirm({ title: 'Delete thread?', okLabel: 'Delete', danger: true, body: <p>{deleteThreadBody(t.comments.length)}</p> })) delThread.mutate({ id: share.id, tid: t.id });
  };
  const removeComment = async (cid: string) => {
    if (t.comments.length === 1) return removeThread();
    if (await confirm({ title: 'Delete comment?', okLabel: 'Delete', danger: true, body: <p>{deleteCommentBody}</p> })) delComment.mutate({ id: share.id, tid: t.id, cid });
  };
  const send = () => reply.mutate({ id: share.id, tid: t.id, body: text.trim() }, { onSuccess: () => setText('') });

  return (
    <li id={`thread-${t.id}`} tabIndex={-1} className={`thread${t.resolved ? ' resolved' : ''}`}>
      {t.resolved ? (
        <button type="button" className="thread-head" aria-expanded={open} onClick={() => setOpen(!open)}>
          Resolved: {quote}
        </button>
      ) : null}
      {open ? (
        <div className="stack">
          {fresh ? <span className="chip-new">New</span> : null}
          {placed ? (
            <button type="button" className="thread-quote" title={t.anchor.exact} onClick={() => onJump(t.id)}>{quote}</button>
          ) : (
            <blockquote className="thread-quote" title={t.anchor.exact}>{quote}</blockquote>
          )}
          <ul className="thread-comments">
            {t.comments.map((c) => (
              <li key={c.id}>
                <div className="row">
                  <b>{c.author}</b>
                  {c.by_owner ? <span className="chip-new">Author</span> : null}
                  <span className="muted grow">{formatWhen(c.at)}</span>
                  <Button sm variant="ghost" aria-label={`Delete comment by ${c.author}`} onClick={() => removeComment(c.id)}>Delete</Button>
                </div>
                <p className="thread-body">{c.body}</p>
              </li>
            ))}
          </ul>
          <label className="sr" htmlFor={fieldId}>Reply</label>
          <textarea id={fieldId} className="f" rows={2} maxLength={MAX_REPLY} placeholder="Reply" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row">
            <Button sm disabled={!text.trim() || reply.isPending} onClick={send}>Reply</Button>
            <Button sm variant="ghost" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: share.id, tid: t.id, resolved: !t.resolved })}>{t.resolved ? 'Reopen' : 'Resolve'}</Button>
            <span className="grow" />
            <Button sm variant="ghost" onClick={removeThread}>Delete thread</Button>
          </div>
        </div>
      ) : null}
    </li>
  );
}

/**
 * The share's threads next to the PRD text: open ones in text order, resolved ones collapsed, then Outdated.
 * `placements` is null in Edit mode and before the first placement; every thread is then listed by its state alone.
 * `extra` is the header slot for "Send open comments" and gets the Outdated thread ids.
 */
export function ThreadRail({ share, placements, baseline, onJump, extra }: {
  share: Share;
  placements: Placements | null;
  baseline: string | null;
  onJump: (id: string) => void;
  extra?: (outdatedIds: string[]) => ReactNode;
}) {
  const confirm = useConfirm();
  const delRecord = useDeleteShareRecord();
  const ended = share.state === 'ended';
  const { threads } = share;
  if (ended && !threads.length) return null;

  const spanOf = (t: ShareThread) => placements?.spans.get(t.id);
  const isOutdated = (t: ShareThread) => placements !== null && spanOf(t) === null;
  const byText = (a: ShareThread, b: ShareThread) => (spanOf(a)?.start ?? Infinity) - (spanOf(b)?.start ?? Infinity);
  const live = threads.filter((t) => !isOutdated(t));
  const open = live.filter((t) => !t.resolved).sort(byText);
  const resolved = live.filter((t) => t.resolved).sort(byText);
  const outdated = threads.filter(isOutdated);
  const outdatedIds = outdated.map((t) => t.id);
  const card = (t: ShareThread) => <ThreadCard key={t.id} share={share} t={t} placed={!!spanOf(t)} isNew={isNew(t, baseline)} onJump={onJump} />;

  const removeRecord = async () => {
    if (await confirm({ title: 'Delete share record?', okLabel: 'Delete', danger: true, body: <p>{deleteRecordBody(threads.length)}</p> })) delRecord.mutate(share.id);
  };

  return (
    <section className="box thread-rail" aria-label="Comments">
      <div className="row">
        <h3 className="grow">Comments</h3>
        {extra?.(outdatedIds)}
        {ended ? <Button sm variant="danger" disabled={delRecord.isPending} onClick={removeRecord}>Delete share record</Button> : null}
      </div>
      {!threads.length ? <p className="muted">No comments yet</p> : null}
      <ul className="thread-list">{open.map(card)}</ul>
      <ul className="thread-list">{resolved.map(card)}</ul>
      {outdated.length ? (
        <>
          <h4>Outdated</h4>
          <ul className="thread-list">{outdated.map(card)}</ul>
        </>
      ) : null}
    </section>
  );
}
