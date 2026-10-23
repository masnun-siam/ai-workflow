import type { FeatureIssue } from '../lib/features';
import { IssueTable } from './IssuesTab';

/** Open issues outside any feature, grouped by status. */
export function SmallChangesTab({ repo, issues }: { repo: string; issues: FeatureIssue[] }) {
  return issues.length ? (
    <IssueTable issues={issues} repo={repo} />
  ) : (
    <p className="muted">Nothing outside a feature. Describe a bug or small change to start one.</p>
  );
}
