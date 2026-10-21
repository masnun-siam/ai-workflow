import { countBy, type Feature } from '../lib/features';
import { ISSUE, ISSUE_ORDER, STAGES, stageIdx } from '../lib/vocab';

/** The stage stepper (planning stages as bars, Building as issue counts by status) with the issue legend (FR-12). */
export function Stepper({ f }: { f: Pick<Feature, 'stage' | 'issues'> }) {
  const i = stageIdx(f.stage);
  const c = countBy(f.issues);
  const n = f.issues.length || 1;
  return (
    <div className="stack" style={{ gap: 10 }}>
      <ol className="stepper" aria-label="Stages" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {STAGES.map((s, k) => (
          <li key={s.id} className={`step t-${s.tone} ${k < i ? 'done' : k === i ? 'now' : ''}`} aria-current={k === i ? 'step' : undefined}>
            {s.id === 'building' ? (
              <div className="work">
                {k <= i ? ISSUE_ORDER.filter((x) => c[x]).map((x) => <span key={x} style={{ width: `${((c[x] ?? 0) / n) * 100}%`, background: ISSUE[x].color }} />) : null}
              </div>
            ) : (
              <div className="bar" />
            )}
            <div className="lab">{s.label}{k < i ? <span className="sr"> (done)</span> : null}</div>
          </li>
        ))}
      </ol>
      {i >= 3 && f.issues.length ? (
        <div className="legend">
          {ISSUE_ORDER.filter((x) => c[x]).map((x) => (
            <span key={x}><i style={{ background: ISSUE[x].color }} />{c[x]} {ISSUE[x].label.toLowerCase()}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
