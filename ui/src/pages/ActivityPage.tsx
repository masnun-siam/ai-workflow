// FR-19: live sessions as cards, history as a table with search and filters, cost strip, clean up.
import { useMemo, useState } from 'react';
import { useRepos, useSessions, useSettings } from '../api/hooks';
import type { Session } from '../api/types';
import { Banner, Button, EmptyState, Icon, SessionChip } from '../components';
import { CleanupDialog } from '../activity/CleanupDialog';
import { forText, issueOf, SessionTable } from '../activity/SessionTable';
import { clockText, duration, money, sessionLabel, sessionSlug, untilText } from '../lib/format';
import { RepoSelect } from '../shell/RepoSelect';
import { routes } from '../lib/routes';
import { isLive } from '../lib/vocab';

const PAGE = 50;
const sameDay = (iso: string, now: Date) => new Date(iso).toDateString() === now.toDateString();

export function ActivityPage() {
  const q = useSessions();
  const repos = useRepos().data?.repos ?? [];
  const accounts = useSettings().data?.commands ?? [];
  const [search, setSearch] = useState('');
  const [result, setResult] = useState('all');
  const [repo, setRepo] = useState('');
  const [group, setGroup] = useState(false);
  const [shown, setShown] = useState(PAGE);
  const [cleaning, setCleaning] = useState(false);

  const all: Session[] = q.data?.sessions ?? [];
  const sorted = useMemo(() => [...all].sort((a, b) => (b.started_at ?? '').localeCompare(a.started_at ?? '')), [all]);
  const live = sorted.filter((s) => isLive(s.outcome));
  const hist = useMemo(() => {
    const t = search.trim().toLowerCase().replace(/^#/, '');
    return sorted.filter(
      (s) =>
        !isLive(s.outcome) &&
        (result === 'all' || s.outcome === result) &&
        (!repo || sessionSlug(s) === repo) &&
        (!t || `${s.command} ${issueOf(s) ?? ''} ${forText(s)}`.toLowerCase().includes(t)),
    );
  }, [sorted, search, result, repo]);

  const now = new Date();
  const cost = (f: (s: Session) => boolean) => all.filter(f).reduce((a, s) => a + (s.cost ?? 0), 0);
  const today = cost((s) => sameDay(s.started_at, now));
  const week = cost((s) => now.getTime() - Date.parse(s.started_at) < 7 * 86400000);
  const label = (cmd: string | null) => accounts.find((c) => c.cmd === cmd)?.label ?? '';

  return (
    <div className="content-inner">
      <div className="page-head">
        <div className="grow">
          <h1>Activity</h1>
          <p className="sub">Every Claude session the UI started. {money(today)} spent today, {money(week)} in the last 7 days.</p>
        </div>
        <Button onClick={() => setCleaning(true)}><Icon n="trash" />Clean up old</Button>
      </div>
      {q.isError ? <Banner tone="bad" icon="alert" action={<Button sm onClick={() => void q.refetch()}>Retry</Button>}>Could not load sessions. {q.error.message}</Banner> : null}
      <section aria-label="Live">
        <div className="group-h"><h2>Live</h2><span className="n">{live.length}</span></div>
        {live.length ? (
          <div className="live-grid">
            {live.map((s) => (
              <div key={s.id} className={`live-card${s.outcome === 'waiting' ? ' you' : ''}`}>
                <div className="row"><SessionChip s={s.outcome} /><span className="grow" /><span className="faint" style={{ fontSize: 12 }}>{duration(s.started_at)}</span></div>
                <a className="cmd" href={`#${routes.session(s.id)}`} style={{ textDecoration: 'none' }}>{sessionLabel(s.command)}</a>
                <div className="muted" style={{ fontSize: 13 }}>{forText(s)}</div>
                <div className="muted" style={{ fontSize: 12.5 }}>
                  {s.outcome === 'limited' ? `${label(s.claude_cmd) || 'Account'} limited${s.limit_resets_at ? `, resumes at ${clockText(s.limit_resets_at)} (${untilText(s.limit_resets_at)})` : ''}` : s.outcome === 'queued' ? (s.note ?? 'Queued') : `${label(s.claude_cmd) ? `${label(s.claude_cmd)} account · ` : ''}${money(s.cost)}`}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState icon="activity" title="Nothing running">Start something with N, or from a feature or issue.</EmptyState>
        )}
      </section>
      <section className="stack" style={{ gap: 10 }} aria-label="History">
        <div className="row wrap">
          <h2>History</h2><span className="grow" />
          <input className="f" style={{ width: 220 }} placeholder="Search command or #issue" aria-label="Search history" value={search} onChange={(e) => { setSearch(e.target.value); setShown(PAGE); }} />
          <select className="f" style={{ width: 140 }} aria-label="Result" value={result} onChange={(e) => { setResult(e.target.value); setShown(PAGE); }}>
            <option value="all">All results</option><option value="done">Done</option><option value="failed">Failed</option><option value="stopped">Stopped</option>
          </select>
          <RepoSelect repos={repos} value={repo} onChange={(v) => { setRepo(v); setShown(PAGE); }} label="Repo" width={160} extrasBefore={[{ value: '', label: 'All repos' }]} />
          <label className="row" style={{ gap: 6 }}><input type="checkbox" checked={group} onChange={(e) => setGroup(e.target.checked)} />Group by issue</label>
        </div>
        <SessionTable rows={hist.slice(0, shown)} groupByIssue={group} />
        {hist.length > shown ? <div><Button onClick={() => setShown(shown + PAGE)}>Show more ({hist.length - shown} left)</Button></div> : null}
      </section>
      <CleanupDialog open={cleaning} onClose={() => setCleaning(false)} />
    </div>
  );
}
