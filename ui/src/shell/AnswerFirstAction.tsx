import { useNavigate } from 'react-router-dom';
import { useSessions } from '../api/hooks';
import { routes } from '../lib/routes';
import { useRepo } from './useRepo';
import { useAction } from './shortcuts';

/** Palette action (from any page): open the oldest session waiting on an answer. Disabled, so absent, when none is. */
export function AnswerFirstAction() {
  const navigate = useNavigate();
  const { link } = useRepo();
  const sessions = useSessions().data?.sessions ?? [];
  const first = sessions
    .filter((s) => s.waiting && s.pending_question)
    .sort((a, b) => (a.started_at ?? '').localeCompare(b.started_at ?? ''))[0];
  useAction({ label: 'Answer the first waiting question', run: () => first && navigate(link(routes.session(first.id))), disabled: !first });
  return null;
}
