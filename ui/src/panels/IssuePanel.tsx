import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useComment, useDelivery, useIssue, usePlanning, useSessions, useSetIssueState } from '../api/hooks';
import type { DeliveryCard, IssueDetail } from '../api/types';
import { useStarter } from '../board/actions';
import { IssueAction } from '../board/IssueAction';
import { IssueSignals } from '../board/IssueSignals';
import { Button, Chip, EmptyState, ExtButton, IssueChip, SessionChip, toast } from '../components';
import { joinFeatures } from '../lib/features';
import { formatWhen, sessionLabel, sessionSlug } from '../lib/format';
import { routes } from '../lib/routes';
import { issueStatus } from '../lib/vocab';
import { useRepo } from '../shell/useRepo';
import { PanelFrame } from './DetailPanel';
import { usePanel } from './PanelContext';
import './panels.css';

export const who = (a: unknown): string => (typeof a === 'string' ? a : a && typeof a === 'object' && 'login' in a ? String((a as { login: unknown }).login) : 'ghost');

const stateText = (d: IssueDetail) => (d.is_pr ? (d.state === 'open' ? 'PR open' : 'PR closed') : d.state === 'open' ? 'Open' : d.state_reason === 'not_planned' ? 'Closed as not planned' : 'Closed');

export function IssuePanel({ repo, n }: { repo: string; n: number }) {
  const q = useIssue(repo, n);
  const del = useDelivery(repo);
  const plan = usePlanning(repo);
  const sess = useSessions().data?.sessions ?? [];
  const panel = usePanel();
  const { link } = useRepo();
  const setState = useSetIssueState();
  const comment = useComment();
  const starter = useStarter();
  const [text, setText] = useState('');

  const lane = del.data?.lanes.find((l) => l.cards.some((c) => c.n === n));
  const card: DeliveryCard | undefined = lane?.cards.find((c) => c.n === n);
  const feature = lane?.epic != null ? joinFeatures(plan.data?.prds ?? [], del.data?.lanes ?? []).find((f) => f.epic === lane.epic) : undefined;
  const mine = sess.filter((s) => {
    const l = s.link;
    return l && typeof l === 'object' && l.issue === n && (sessionSlug(s) || repo) === repo;
  });
  const d = q.data && { ...q.data, labels: q.data.labels ?? [], assignees: q.data.assignees ?? [], comments: q.data.comments ?? [], comment_count: q.data.comment_count ?? 0 };
  const open = d?.state === 'open';

  if (q.isError)
    return (
      <PanelFrame title={`Issue #${n}`} subtitle={repo}>
        <EmptyState icon="alert" title="Could not load this issue" actions={<Button onClick={() => q.refetch()}>Retry</Button>}>{q.error.message}</EmptyState>
      </PanelFrame>
    );
  if (!d)
    return (
      <PanelFrame title={`Issue #${n}`} subtitle={repo}>
        <p className="muted" role="status">Loading…</p>
      </PanelFrame>
    );

  return (
    <PanelFrame
      title={<>#{n} {d.title}</>}
      subtitle={repo}
      head={
        <div className="row wrap">
          <Chip tone={d.state === 'open' ? 'build' : 'muted'}>{stateText(d)}</Chip>
          {card ? <IssueChip s={issueStatus(card)} /> : null}
          {card ? <IssueAction card={card} repo={repo} autoGrind={del.data?.auto_grind} /> : null}
        </div>
      }
      footer={
        <>
          <label className="sr" htmlFor="issue-comment">Comment</label>
          <textarea id="issue-comment" className="f" rows={2} placeholder="Leave a comment" value={text} onChange={(e) => setText(e.target.value)} />
          <Button variant="primary" disabled={!text.trim() || comment.isPending} onClick={() => comment.mutate({ kind: 'issues', repo, n, text: text.trim() }, { onSuccess: () => { setText(''); toast('Comment posted'); } })}>Comment</Button>
        </>
      }
    >
      <p className="muted" style={{ fontSize: 13 }}>{who(d.author)} opened {formatWhen(d.created_at)}{d.assignees.length ? ` · assigned to ${d.assignees.map(who).join(', ')}` : ''}</p>
      {card ? <IssueSignals card={card} /> : null}
      {feature ? <p>Part of <Link to={link(routes.feature(feature.slug))} onClick={panel.close}>{feature.title}</Link></p> : null}
      {card && card.blocked_by.length ? (
        <p>Blocked by {card.blocked_by.map((b, i) => <span key={b}>{i ? ', ' : ''}<button type="button" className="linkish" style={{ textDecoration: 'underline' }} onClick={() => panel.open({ kind: 'issue', repo, n: b })}>#{b}</button></span>)}</p>
      ) : null}
      {card?.pr ? (
        <div className="box">
          <div className="row"><b>PR #{card.pr.n}</b>{card.pr.draft ? <Chip>Draft</Chip> : null}<span className="grow" /><Button sm onClick={() => panel.open({ kind: 'pr', repo, n: card.pr!.n })}>Open PR</Button></div>
        </div>
      ) : null}
      <div className="row wrap">
        {open ? (
          <>
            {!d.is_pr ? <Button sm disabled={starter.pending} onClick={() => starter.startBoard({ repo, skill: 'refine-issues', arg: String(n), via: 'headless' })}>{d.labels.some((l) => l.name === 'refined') ? 'Refine again' : 'Refine'}</Button> : null}
            {!d.is_pr ? <Button sm disabled={setState.isPending} onClick={() => setState.mutate({ repo, n, state: 'closed', reason: 'completed' })}>Close as completed</Button> : null}
            {!d.is_pr ? <Button sm disabled={setState.isPending} onClick={() => setState.mutate({ repo, n, state: 'closed', reason: 'not_planned' })}>Close as not planned</Button> : null}
          </>
        ) : !d.is_pr ? (
          <Button sm disabled={setState.isPending} onClick={() => setState.mutate({ repo, n, state: 'open' })}>Reopen</Button>
        ) : null}
        <ExtButton sm href={d.url}>Open on GitHub</ExtButton>
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
    </PanelFrame>
  );
}
