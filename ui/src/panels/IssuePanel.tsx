import { useState } from 'react';
import { useAction } from '../shell/shortcuts';
import { Link } from 'react-router-dom';
import { useComment, useDelivery, useIssue, usePlanning, useSessions, useSetIssueState } from '../api/hooks';
import type { DeliveryCard, IssueDetail } from '../api/types';
import { useStarter } from '../board/actions';
import { IssueSignals } from '../board/IssueSignals';
import { Button, EmptyState, ExtButton, SessionChip, toast } from '../components';
import { joinFeatures } from '../lib/features';
import { formatWhen, sessionLabel, sessionSlug } from '../lib/format';
import { routes } from '../lib/routes';
import { useRepo } from '../shell/useRepo';
import { usePanel } from './PanelContext';
import { useFollowups } from './useFollowups';
import './panels.css';
import { PLAN_RUN } from '../lib/vocab';

export const who = (a: unknown): string => (typeof a === 'string' ? a : a && typeof a === 'object' && 'login' in a ? String((a as { login: unknown }).login) : 'ghost');

export const issueStateText = (d: IssueDetail) => (d.is_pr ? (d.state === 'open' ? 'PR open' : 'PR closed') : d.state === 'open' ? 'Open' : d.state_reason === 'not_planned' ? 'Closed as not planned' : 'Closed');

/** `C`: puts focus in the comment box with this id. Render it inside the tab that holds the box, so the key exists only while the box is on screen. */
export function FocusComment({ id }: { id: string }) {
  useAction({ label: 'Comment', key: 'c', run: () => document.getElementById(id)?.focus() });
  return null;
}

/** The Issue tab of the work panel: the issue, its sessions, comments and the comment box. */
export function IssueTab({ repo, n, card }: { repo: string; n: number; card?: DeliveryCard }) {
  const q = useIssue(repo, n);
  const del = useDelivery(repo);
  const plan = usePlanning(repo);
  const sess = useSessions().data?.sessions ?? [];
  const panel = usePanel();
  const { link } = useRepo();
  const setState = useSetIssueState();
  const comment = useComment();
  const starter = useStarter();
  const followups = useFollowups(repo);
  const [text, setText] = useState('');

  const lane = del.data?.lanes.find((l) => l.cards.some((c) => c.n === n));
  const feature = lane?.epic != null ? joinFeatures(plan.data?.prds ?? [], del.data?.lanes ?? []).find((f) => f.epic === lane.epic) : undefined;
  const mine = sess.filter((s) => {
    const l = s.link;
    return l && typeof l === 'object' && l.issue === n && (sessionSlug(s) || repo) === repo;
  });
  const d = q.data && { ...q.data, labels: q.data.labels ?? [], assignees: q.data.assignees ?? [], comments: q.data.comments ?? [], comment_count: q.data.comment_count ?? 0 };
  const open = d?.state === 'open';

  if (q.isError) return <EmptyState icon="alert" title="Could not load this issue" actions={<Button onClick={() => q.refetch()}>Retry</Button>}>{q.error.message}</EmptyState>;
  if (!d) return <p className="muted" role="status">Loading…</p>;

  return (
    <div className="stack">
      <FocusComment id="issue-comment" />
      <p className="muted" style={{ fontSize: 13 }}>{who(d.author)} opened {formatWhen(d.created_at)}{d.assignees.length ? ` · assigned to ${d.assignees.map(who).join(', ')}` : ''}</p>
      {card ? <IssueSignals card={card} /> : null}
      {feature ? <p>Part of <Link to={link(routes.feature(feature.slug))} onClick={panel.close}>{feature.title}</Link></p> : null}
      {card && card.blocked_by.length ? (
        <p>Blocked by {card.blocked_by.map((b, i) => <span key={b}>{i ? ', ' : ''}<button type="button" className="linkish" style={{ textDecoration: 'underline' }} onClick={() => panel.open({ kind: 'issue', repo, n: b })}>#{b}</button></span>)}</p>
      ) : null}
      <div className="row wrap">
        {open ? (
          <>
            {!d.is_pr ? <Button sm shortcut="e" disabled={starter.pending} onClick={() => starter.startBoard({ repo, skill: 'refine-issues', arg: String(n), via: 'headless', ...PLAN_RUN })}>{d.labels.some((l) => l.name === 'refined') ? 'Refine again' : 'Refine'}</Button> : null}
            {!d.is_pr ? <Button sm disabled={setState.isPending} onClick={() => setState.mutate({ repo, n, state: 'closed', reason: 'completed' }, { onSuccess: () => void followups.offer(n, `issue #${n} is closed`) })}>Close as completed</Button> : null}
            {!d.is_pr ? <Button sm disabled={setState.isPending} onClick={() => setState.mutate({ repo, n, state: 'closed', reason: 'not_planned' })}>Close as not planned</Button> : null}
          </>
        ) : !d.is_pr ? (
          <>
            <Button sm disabled={setState.isPending} onClick={() => setState.mutate({ repo, n, state: 'open' })}>Reopen</Button>
            {d.state_reason !== 'not_planned' ? (
              <Button sm disabled={followups.isSent(n)} title={followups.isSent(n) ? 'Follow-ups already sent for this issue' : undefined} onClick={() => void followups.offer(n, `issue #${n} is closed`)}>
                {followups.isSent(n) ? 'Follow-ups sent' : 'Do follow-ups'}
              </Button>
            ) : null}
          </>
        ) : null}
        <ExtButton sm href={d.url}>Issue on GitHub</ExtButton>
      </div>
      {mine.length ? (
        <div className="stack" style={{ gap: 6 }}>
          <h3>Sessions</h3>
          {mine.map((s) => (
            <div key={s.id} className="row"><SessionChip s={s.outcome} /><Link className="mono ellipsis" to={link(routes.session(s.id))} onClick={panel.close}>{sessionLabel(s.command)}</Link></div>
          ))}
        </div>
      ) : null}
      {d.body_html ? <div className="p-html" dangerouslySetInnerHTML={{ __html: d.body_html }} /> : <p className="muted">No description.</p>}
      <h3>{d.comment_count === 0 ? 'No comments' : `${d.comment_count} comment${d.comment_count === 1 ? '' : 's'}`}</h3>
      {d.comments.map((c, i) => (
        <article key={i} className="p-comment">
          <div className="who"><b>{who(c.author)}</b> · {formatWhen(c.created_at)}</div>
          <div className="p-html" dangerouslySetInnerHTML={{ __html: c.body_html }} />
        </article>
      ))}
      {d.comment_count > d.comments.length ? <p className="muted">{d.comment_count - d.comments.length} more on GitHub.</p> : null}
      <label className="sr" htmlFor="issue-comment">Comment on the issue</label>
      <textarea id="issue-comment" className="f" rows={3} placeholder="Leave a comment" value={text} onChange={(e) => setText(e.target.value)} />
      <div><Button disabled={!text.trim() || comment.isPending} onClick={() => comment.mutate({ kind: 'issues', repo, n, text: text.trim() }, { onSuccess: () => { setText(''); toast('Comment posted'); } })}>Comment</Button></div>
    </div>
  );
}
