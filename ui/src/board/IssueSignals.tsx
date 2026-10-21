import type { DeliveryCard } from '../api/types';
import { Chip, CiChip, SessionChip } from '../components';
import { isLive } from '../lib/vocab';

/** Priority, PR, CI, review decision, grind state, live session, last run failed, needs cleanup (FR-13). */
export function IssueSignals({ card }: { card: DeliveryCard }) {
  const pr = card.pr;
  const g = card.grind;
  const s = card.session;
  return (
    <span className="row wrap" style={{ gap: 6 }}>
      {card.priority === 'high' ? <Chip tone="you">High</Chip> : null}
      {pr ? <span className="ref">PR #{pr.n}{pr.draft ? ' draft' : ''}</span> : null}
      {pr ? <CiChip ci={pr.ci} /> : null}
      {pr?.review === 'approved' ? <Chip tone="ship">Approved</Chip> : null}
      {pr?.review === 'changes_requested' ? <Chip tone="review">Changes requested</Chip> : null}
      {g ? <Chip tone={g.state === 'paused' ? 'bad' : 'review'}>{g.state === 'paused' ? 'Grind paused' : `Grind round ${g.round ?? 1}`}</Chip> : null}
      {s && isLive(s.status) && s.status !== 'queued' ? <SessionChip s={s.status} /> : null}
      {card.last_failed ? <Chip tone="bad">Last run failed</Chip> : null}
      {card.needs_cleanup ? <Chip>Needs cleanup</Chip> : null}
    </span>
  );
}
