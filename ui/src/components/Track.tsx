import type { Feature } from '../lib/features';
import { countBy } from '../lib/features';
import { ISSUE, ISSUE_ORDER, STAGES, stageIdx } from '../lib/vocab';

/** The feature progress track: four planning segments, then the build stage as issue counts by status. */
export function Track({ feature }: { feature: Pick<Feature, 'stage' | 'issues'> }) {
  const i = stageIdx(feature.stage);
  const c = countBy(feature.issues);
  const n = feature.issues.length || 1;
  const merged = c.merged ?? 0;
  return (
    <div className="track" role="img" aria-label={i >= 4 && feature.issues.length ? `${STAGES[i].label}: ${merged} of ${feature.issues.length} merged` : STAGES[i].label}>
      <div className="track-bar">
        {STAGES.slice(0, 4).map((s, k) => (
          <i key={s.id} className={`t-${s.tone} ${k < i ? 'done' : k === i ? 'now' : ''}`} />
        ))}
        <span className="work">
          {i >= 4
            ? ISSUE_ORDER.filter((s) => c[s]).map((s) => <span key={s} style={{ width: `${((c[s] ?? 0) / n) * 100}%`, background: ISSUE[s].color }} />)
            : null}
        </span>
      </div>
      <div className="track-cap">{i >= 4 && feature.issues.length ? `${merged} of ${feature.issues.length} merged` : STAGES[i].label}</div>
    </div>
  );
}
