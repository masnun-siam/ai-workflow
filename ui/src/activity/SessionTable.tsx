// The history table, shared by Activity and the Feature page's Sessions tab (FR-16, FR-19, FR-21).
import { Fragment } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Session, SessionLink } from '../api/types';
import { MoreMenu, SessionChip } from '../components';
import { formatWhen, money, sessionLabel, sessionSlug, shortRepo } from '../lib/format';
import { routes } from '../lib/routes';
import { sessionButtons, useSessionActions } from '../session/useSessionActions';

/** The issue number a session works on, from its link. */
export function issueOf(s: Pick<Session, 'link'>): number | null {
  const l = s.link as SessionLink | string | null;
  if (l && typeof l === 'object') return l.issue || null;
  const m = typeof l === 'string' ? /\/(?:issues|pull)\/(\d+)/.exec(l) : null;
  return m ? Number(m[1]) : null;
}
/** What a session is for: "#801", the feature or repo, or the notes vault. */
export function forText(s: Session): string {
  const n = issueOf(s);
  if (n) return `#${n}`;
  if (s.no_repo) return 'Notes vault';
  return shortRepo(sessionSlug(s) || s.repo);
}

export function SessionActions({ s, sm = true }: { s: Session; sm?: boolean }) {
  const nav = useNavigate();
  const a = useSessionActions();
  const { main, entries } = sessionButtons(s, a, (p) => nav(p), sm);
  return (
    <span className="row" style={{ justifyContent: 'flex-end', gap: 4 }}>
      {main}
      <MoreMenu items={entries} sm={sm} label={`More actions for ${sessionLabel(s.command)}`} />
    </span>
  );
}

export function SessionTable({ rows, groupByIssue }: { rows: Session[]; groupByIssue?: boolean }) {
  const nav = useNavigate();
  if (!rows.length) return <p className="muted">No sessions match.</p>;
  const groups: [string, Session[]][] = groupByIssue
    ? [...rows.reduce((m, s) => { const k = issueOf(s) ? `Issue #${issueOf(s)}` : 'No issue'; return m.set(k, [...(m.get(k) ?? []), s]); }, new Map<string, Session[]>())]
    : [['', rows]];
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr><th>Session</th><th className="hide-sm">For</th><th>Started</th><th>Result</th><th className="num hide-sm">Cost</th><th style={{ textAlign: 'right' }}>Action</th></tr>
        </thead>
        <tbody>
          {groups.map(([g, list]) => (
            <Fragment key={g}>
              {g ? <tr className="sub"><td colSpan={6}>{g}</td></tr> : null}
              {list.map((s) => (
                <tr key={s.id} className="click" onClick={() => nav(routes.session(s.id))}>
                  <td className="mono"><a href={`#${routes.session(s.id)}`} onClick={(e) => e.stopPropagation()} className="clamp2" title={sessionLabel(s.command)} style={{ textDecoration: 'none' }}>{sessionLabel(s.command)}</a></td>
                  <td className="hide-sm muted" style={{ whiteSpace: 'nowrap' }}>{forText(s)}</td>
                  <td className="muted" style={{ whiteSpace: 'nowrap' }}>{formatWhen(s.started_at)}</td>
                  <td><SessionChip s={s.outcome} /></td>
                  <td className="num hide-sm">{money(s.cost)}</td>
                  <td style={{ textAlign: 'right' }} onClick={(e) => e.stopPropagation()}><SessionActions s={s} /></td>
                </tr>
              ))}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
