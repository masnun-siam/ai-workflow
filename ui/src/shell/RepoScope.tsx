import { useRepos } from '../api/hooks';
import { RepoSelect } from './RepoSelect';

/** Filter a page to one repo or to all of them (`?only=`, from useRepoFilter): the same dropdown as Inbox, Small changes and Activity. */
export function RepoScope({ only, setOnly, label }: { only: string; setOnly: (slug: string) => void; label: string }) {
  const repos = useRepos().data?.repos ?? [];
  return <RepoSelect repos={repos} value={only} onChange={setOnly} label={label} width={180} extrasBefore={[{ value: '', label: 'All repos' }]} />;
}
