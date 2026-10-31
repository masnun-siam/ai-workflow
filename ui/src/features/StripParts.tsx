import { countBy, issueBuckets, type FeatureIssue } from '../lib/features';
import { STAGES } from '../lib/vocab';

/** The six stages as ticks, up to `at`. */
export function StageTicks({ at }: { at: number }) {
  return <span className="ticks" aria-hidden="true">{STAGES.map((s, k) => <i key={s.id} className={k < at ? 'past' : k === at ? 'now' : ''} />)}</span>;
}

/** merged/total and the bar of a feature's issues by state; `you` are the issues a dispatch stopped on. */
export function IssueBar({ issues, you }: { issues: FeatureIssue[]; you: Set<number> }) {
  if (!issues.length) return <span className="muted">No issues yet</span>;
  const merged = countBy(issues).merged ?? 0;
  return (
    <>
      <b>{merged}/{issues.length}</b>
      <span className="ibar" role="img" aria-label={`${merged} of ${issues.length} issues merged`}>
        {issueBuckets(issues, you).reverse().map((b) => <i key={b.id} className={`s-${b.id}`} style={{ flexGrow: b.items.length }} title={`${b.items.length} ${b.label.toLowerCase()}`} />)}
      </span>
    </>
  );
}
