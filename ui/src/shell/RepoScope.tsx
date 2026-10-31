import { shortRepo } from '../lib/format';

/** Filter a page to the repo in hand or to all of them (`?only=`, from useRepoFilter). */
export function RepoScope({ repo, only, setOnly, label }: { repo: string; only: string; setOnly: (slug: string) => void; label: string }) {
  const here = only || repo;
  return (
    <div className="scope" role="group" aria-label={label}>
      {here ? <button type="button" aria-pressed={!!only} onClick={() => setOnly(here)}>{shortRepo(here)}</button> : null}
      <button type="button" aria-pressed={!only} onClick={() => setOnly('')}>All repos</button>
    </div>
  );
}
