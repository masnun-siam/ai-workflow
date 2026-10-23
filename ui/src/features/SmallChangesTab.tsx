import type { FeatureIssue } from '../lib/features';
import { IssueTable } from './IssuesTab';
import { PendingRows } from './PendingRows';
import { SmallChangeBox } from './SmallChangeBox';
import { SMALL_CHANGE_LOCK, type PendingChange } from './smallChange';

/** Open issues outside any feature, grouped by status, under the live small-change sessions. */
export function SmallChangesTab({ repo, issues, pending }: { repo: string; issues: FeatureIssue[]; pending: PendingChange[] }) {
  return (
    <>
      <SmallChangeBox repo={repo} />
      <PendingRows pending={pending} />
      {issues.length ? (
        <IssueTable issues={issues} repo={repo} lockRefine={pending.length ? SMALL_CHANGE_LOCK : undefined} />
      ) : pending.length ? null : (
        <p className="muted">Nothing outside a feature. Describe a bug or small change to start one.</p>
      )}
    </>
  );
}
