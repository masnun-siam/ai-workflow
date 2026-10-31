import type { CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import { countBy, type Feature } from '../lib/features';
import { routes } from '../lib/routes';
import { STAGES, stageIdx } from '../lib/vocab';
import { useRepo } from '../shell/useRepo';

function note(f: Feature, you: boolean) {
  if (you) return 'Needs you';
  if (f.stage === 'building' || f.stage === 'tasks') {
    const merged = countBy(f.issues).merged ?? 0;
    return f.issues.length ? `${merged} of ${f.issues.length} merged` : STAGES[stageIdx(f.stage)].label;
  }
  return STAGES[stageIdx(f.stage)].label;
}

/** One feature as a line through the six stages: solid up to where it is, dotted after. */
export function MetroLine({ f, color, you = false, big = false, link = true }: { f: Feature; color: string; you?: boolean; big?: boolean; link?: boolean }) {
  const { link: to } = useRepo();
  const at = stageIdx(f.stage);
  return (
    <div className={`metro-line${big ? ' solo' : ''}${you ? ' you' : ''}`} style={{ '--lc': color, '--at': at } as CSSProperties}>
      <div className="metro-name">
        {link ? <Link to={to(routes.feature(f.slug))}>{f.title}</Link> : <b>{f.title}</b>}
        <span>{note(f, you)}</span>
      </div>
      <ol className="metro-track" aria-label={`${f.title}: ${STAGES[at].label}`}>
        {STAGES.map((s, k) => (
          <li key={s.id} className={k < at ? 'done' : k === at ? 'now' : 'todo'} aria-current={k === at ? 'step' : undefined}>
            <i />
            {big ? <span>{s.label}</span> : <span className="sr">{s.label}</span>}
          </li>
        ))}
      </ol>
    </div>
  );
}
