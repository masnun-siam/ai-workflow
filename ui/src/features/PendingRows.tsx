import { useNavigate } from 'react-router-dom';
import { Button, Chip } from '../components';
import { routes } from '../lib/routes';
import { useRepo } from '../shell/useRepo';
import type { PendingChange } from './smallChange';

const STATE = { queued: { label: 'Queued', tone: 'muted' }, waiting: { label: 'Needs you', tone: 'you' } } as const;

/** Live small-change create sessions, shown above the issue list until they end. */
export function PendingRows({ pending }: { pending: PendingChange[] }) {
  const navigate = useNavigate();
  const { link } = useRepo();
  return (
    <div className="list">
      {pending.map((p) => {
        const st = p.status === 'queued' || p.status === 'waiting' ? STATE[p.status] : { label: 'Creating…', tone: 'build' as const };
        const open = () => navigate(link(routes.session(p.id)));
        return (
          <div key={p.id} className="frow">
            <div style={{ minWidth: 0 }}><div className="ftitle pending-text" title={p.text}>{p.text}</div></div>
            <div><Chip tone={st.tone} live={st.label === 'Creating…'}>{st.label}</Chip></div>
            <div className="fnext">
              {p.status === 'waiting' ? <Button sm variant="you" onClick={open}>Answer</Button> : <Button sm onClick={open}>Watch</Button>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
