// "Resolve conflicts" for a PR that conflicts with its base: starts one session that merges the base in,
// resolves, verifies and pushes. While it runs the button is a "Resolving…" link to that session.
// Shared by the PR panel, the Inbox and the Board/Issues row action.
import { useSessions, useStartSession } from '../api/hooks';
import { Button, LinkButton, toast } from '../components';
import { routes } from '../lib/routes';
import { isLive } from '../lib/vocab';
import { useRepo } from '../shell/useRepo';

const PREFIX = 'Resolve the merge conflicts on ';

export const resolveText = (url: string) =>
  `${PREFIX}${url} . Find its head and base branches with gh pr view. Work in the git worktree that has the head ` +
  `branch checked out (git worktree list); if there is none, add one. Fetch, then merge origin/<base> into the head ` +
  `branch: never rebase and never force-push. Resolve every conflict keeping the intent of both sides, run ` +
  `/ai-workflow:verifier-locally and fix what it reports, commit the merge and push to the head branch. Do not merge ` +
  `the PR. Report what conflicted and how you resolved it.`;

export function ResolveConflicts({ repo, url, n, primary }: { repo: string; url: string; n: number; primary?: boolean }) {
  const sessions = useSessions().data?.sessions ?? [];
  const start = useStartSession();
  const { link } = useRepo();
  const live = sessions.find((s) => isLive(s.outcome) && s.command.startsWith(`${PREFIX}${url} `));
  if (live) return <LinkButton sm to={link(routes.session(live.id))} onClick={(e) => e.stopPropagation()}>Resolving…</LinkButton>;
  return (
    <Button
      sm
      variant={primary ? 'primary' : 'default'}
      disabled={start.isPending}
      onClick={(e) => {
        e.stopPropagation();
        start.mutate({ repo, text: resolveText(url) }, { onSuccess: () => toast(`Resolving conflicts on PR #${n}`) });
      }}
    >
      Resolve conflicts
    </Button>
  );
}
