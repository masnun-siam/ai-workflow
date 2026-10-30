// The run's six phases in order, the current one marked, each with a link to its session. Used by the Inbox cards and the session page.
import { Link } from 'react-router-dom';
import type { BootstrapPhase, BootstrapRun } from '../api/types';
import { Chip } from '../components';
import { routes } from '../lib/routes';
import type { Tone } from '../lib/vocab';

const STATE: Record<BootstrapPhase['state'], { label: string; tone: Tone }> = {
  done: { label: 'Done', tone: 'ship' },
  running: { label: 'Running', tone: 'build' },
  failed: { label: 'Failed', tone: 'bad' },
  pending: { label: 'Pending', tone: 'muted' },
};

/** The running phase, else the failed one, else (a waiting run) the first pending one. */
const currentOf = (phases: BootstrapPhase[]) =>
  (phases.find((p) => p.state === 'running') ?? phases.find((p) => p.state === 'failed') ?? phases.find((p) => p.state === 'pending'))?.name;

export function PhaseStrip({ run, here }: { run: BootstrapRun; here?: string }) {
  const now = run.state === 'done' || run.state === 'ended' ? undefined : currentOf(run.phases);
  return (
    <ol className="phase-strip" aria-label="Bootstrap phases">
      {run.phases.map((p) => {
        const st = STATE[p.state];
        return (
          <li key={p.name} className={`phase${p.name === now ? ' now' : ''}`} aria-current={p.name === now ? 'step' : undefined}>
            {p.session_id && p.session_id === here ? <span>{p.name} (this session)</span> : p.session_id ? <Link to={routes.session(p.session_id)}>{p.name}</Link> : <span>{p.name}</span>}
            <Chip tone={st.tone} live={p.state === 'running'}>{st.label}</Chip>
          </li>
        );
      })}
    </ol>
  );
}
