// FR-7, FR-8, FR-10 and the Away summary (FR-26): everything that needs the user, across repos.
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAfkDismiss, useInbox, useRepos, useSessions, needsYouCount } from '../api/hooks';
import type { AfkState } from '../api/types';
import { Banner, Button, Chip, EmptyState } from '../components';
import { ItemRow, useInboxActions } from '../inbox/items';
import { clockText, shortRepo } from '../lib/format';
import { routes } from '../lib/routes';
import { INBOX_GROUPS } from '../lib/vocab';
import { PublishDialog } from '../repos/PublishDialog';

const KIND: Record<string, string> = { answer: 'Answered', 'skip-ci': 'Skipped CI', retry: 'Retried' };

function AwaySummary({ s }: { s: NonNullable<AfkState['summary']> }) {
  const dismiss = useAfkDismiss();
  const log = (s.log ?? []) as { at?: number; kind?: string; sid?: string; command?: string; question?: string; picked?: string }[];
  return (
    <Banner tone="away" icon="moon" action={<Button sm onClick={() => dismiss.mutate()}>Dismiss</Button>}>
      <div className="stack" style={{ gap: 8 }}>
        <p>
          <b>While you were away ({clockText(s.started)}{s.ended ? `–${clockText(s.ended)}` : ''})</b>: {log.length} thing{log.length === 1 ? '' : 's'} handled, {s.held} held for you.
        </p>
        {log.length ? (
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {log.map((l, k) => (
              <li key={k}>
                {l.at ? <span className="faint">{clockText(l.at)} </span> : null}
                {KIND[l.kind ?? ''] ?? l.kind} {l.sid ? <Link to={routes.session(l.sid)}>{l.command ?? 'session'}</Link> : l.command}
                {l.picked ? <span className="muted"> · {l.picked}</span> : null}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Banner>
  );
}

export function InboxPage() {
  const [filter, setFilter] = useState('');
  const q = useInbox(filter || undefined);
  const repos = useRepos().data?.repos ?? [];
  const sessions = useSessions().data?.sessions ?? [];
  const a = useInboxActions();
  const [openKey, setOpen] = useState<string | null | undefined>(undefined);
  const [publishing, setPublishing] = useState('');

  const items = q.data?.items ?? [];
  const count = needsYouCount(items);
  const working = sessions.filter((s) => s.outcome === 'starting' || s.outcome === 'running').length;
  const firstAnswer = items.find((i) => i.type === 'question')?.key ?? null;
  const open = openKey === undefined ? firstAnswer : openKey;
  const afk = q.data?.afk;

  return (
    <div className="content-inner">
      <div className="page-head">
        <div className="grow">
          <h1>Inbox</h1>
          <p className="sub">
            {count ? `${count} thing${count === 1 ? '' : 's'} need${count === 1 ? 's' : ''} you${filter ? '' : ' across your repos'}. ` : 'Nothing needs you. '}
            {working === 1 ? '1 session is working on its own.' : `${working} sessions are working on their own.`}
          </p>
        </div>
        {afk?.active ? <Chip tone="away">Away mode: answers held for review below</Chip> : null}
        <select className="f" style={{ width: 180 }} aria-label="Repo filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All repos</option>
          {repos.map((r) => (<option key={r.slug} value={r.slug}>{shortRepo(r.slug)}</option>))}
        </select>
      </div>
      {afk?.summary ? <AwaySummary s={afk.summary} /> : null}
      {q.isError ? (
        <Banner tone="bad" icon="alert" action={<Button sm onClick={() => void q.refetch()}>Retry</Button>}>Could not load the inbox. {q.error.message}</Banner>
      ) : null}
      {q.data?.stale?.length ? (
        <Banner tone="muted" icon="clock">
          GitHub data for {q.data.stale.length} repo{q.data.stale.length === 1 ? '' : 's'} is still loading, so merge-ready PRs may be missing.
          {q.data.stale.length <= 3 ? (
            <> ({q.data.stale.map(shortRepo).join(', ')})</>
          ) : (
            <details><summary>Which repos</summary>{q.data.stale.map(shortRepo).join(', ')}</details>
          )}
        </Banner>
      ) : null}
      {q.isLoading ? <div className="skel" style={{ height: 120 }} /> : null}
      {q.data && !count ? (
        <EmptyState icon="inbox" title="All clear" actions={<Link className="btn" to={routes.activity}>See what is running</Link>}>
          Questions, approvals, merges and failures show up here the moment they need you. {working === 1 ? '1 session is working.' : `${working} sessions are working.`}
        </EmptyState>
      ) : null}
      {INBOX_GROUPS.map(({ id, label }) => {
        const g = items.filter((i) => i.group === id);
        if (!g.length) return null;
        return (
          <section key={id} aria-label={label}>
            <div className="group-h"><h2>{label}</h2><span className="n">{g.length}</span></div>
            <div className="list">
              {g.map((it) => (
                <ItemRow key={it.key} item={it} a={a} open={open === it.key} toggle={() => setOpen(open === it.key ? null : it.key)} publish={setPublishing} />
              ))}
            </div>
          </section>
        );
      })}
      <PublishDialog open={!!publishing} slug={publishing} onClose={() => setPublishing('')} />
    </div>
  );
}
