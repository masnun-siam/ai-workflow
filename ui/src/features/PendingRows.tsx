import { useNavigate } from 'react-router-dom';
import { Button, Chip } from '../components';
import { KeyScope } from '../shell/shortcuts';
import { routes } from '../lib/routes';
import { useRepo } from '../shell/useRepo';
import type { IssueSelection } from './IssuesTab';
import type { PendingChange } from './smallChange';

const STATE = { queued: { label: 'Queued', tone: 'muted' }, waiting: { label: 'Needs you', tone: 'you' } } as const;

/** Live small-change create sessions, shown above the issue list until they end. */
export function PendingRows({ pending, selection }: { pending: PendingChange[]; selection?: IssueSelection }) {
  const navigate = useNavigate();
  const { link } = useRepo();
  if (!pending.length) return null;
  return (
    <div className="list">
      {pending.map((p) => {
        const st = p.status === 'queued' || p.status === 'waiting' ? STATE[p.status] : { label: 'Creating…', tone: 'build' as const };
        const open = () => navigate(link(routes.session(p.id)));
        const key = `p:${p.id}`;
        return (
          <div key={p.id} className="frow pending" {...selection?.rowProps(key)}>
            <div style={{ minWidth: 0 }}><div className="ftitle pending-text" title={p.text}>{p.text}</div></div>
            <div><Chip tone={st.tone} live={st.label === 'Creating…'}>{st.label}</Chip></div>
            <div />
            <KeyScope level="row" active={selection?.selected === key} name={p.text}>
              <div className="fnext">
                {p.status === 'waiting' ? <Button sm variant="you" shortcut="a" onClick={open}>Answer</Button> : <Button sm onClick={open}>Watch</Button>}
              </div>
            </KeyScope>
          </div>
        );
      })}
    </div>
  );
}
