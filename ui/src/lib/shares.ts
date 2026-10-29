// The Share popover's rules and exact confirm strings, in one place so the UI and its tests agree.
export const SHARE_WARNING = 'The PRD text is public as written, including its header and any paths';
export const NOT_SHAREABLE = 'Only Draft or In review PRDs can be shared';

export const isShareable = (status: string) => status === 'Draft' || status === 'In review';
export const approvalsLabel = (n: number) => (n === 1 ? '1 approval' : `${n} approvals`);
export const commentsLabel = (n: number) => (n === 1 ? '1 comment' : `${n} comments`);
export const clearsClause = (n: number) => (n > 0 ? `clears the ${approvalsLabel(n)}` : '');
export const stopBody = (n: number) => `Reviewers lose access. Sharing again makes a new link${n > 0 ? ` and ${clearsClause(n)}` : ''}.`;
export const shareBody = (n: number) => `${SHARE_WARNING}.${n > 0 ? ` Sharing again ${clearsClause(n)}.` : ''}`;
export const removeBody = (name: string) => `Remove ${name}'s approval? This cannot be undone.`;
export const threadsLabel = (n: number) => (n === 1 ? '1 thread' : `${n} threads`);
export const deleteCommentBody = 'Delete this comment? Reviewers will no longer see it. This cannot be undone.';
export const deleteThreadBody = (n: number) => `Delete this thread and its ${commentsLabel(n)}? This cannot be undone.`;
export const deleteRecordBody = (n: number) => `Delete this share with its ${threadsLabel(n)} and approvals? This cannot be undone.`;
export const MAX_REPLY = 2000;
