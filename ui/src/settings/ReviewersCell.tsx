import * as PO from '@radix-ui/react-popover';
import type { RepoSettings, Reviewer } from '../api/types';
import { Button, Chip } from '../components';
import { routes } from '../lib/routes';

/** Why an entry is no use on this repo's path ("" when it is), and whether its login is learned later. */
function hints(r: Reviewer, path: RepoSettings['path']) {
  if (path === 'slack' && !r.slack_id) return { off: 'not used: no Slack id', learn: false };
  if (path === 'github' && !r.github_login) return { off: 'not used: no GitHub login', learn: false };
  return { off: '', learn: path === 'slack' && !r.github_login };
}

/** The Default cell's text: the active names, or what a grind does with none. */
function defaultText(names: string[], path: RepoSettings['path'], botLabel: string | null | undefined) {
  if (names.length) return `Default (${names.join(', ')})`;
  if (path === 'slack') return `Default (none, mentions ${botLabel ?? 'the channels.json bot'})`;
  if (path === 'github') return 'Default (none, grinding skips)';
  return 'Default (none)';
}

/** Reviewers: Default (the active set) or the repo's override, and a popover of ticks plus Use default. */
export function ReviewersCell({ slug, row, reviewers, active, botLabel, disabled, onSave }: {
  slug: string;
  row: RepoSettings;
  reviewers: Reviewer[];
  active: string[];
  botLabel: string | null | undefined;
  disabled: boolean;
  onSave: (v: string[] | null) => void;
}) {
  if (!reviewers.length) return <span className="muted">Add reviewers in <a href={`#${routes.settings('reviewers')}`}>Settings → Reviewers</a></span>;
  const known = new Set(reviewers.map((r) => r.id));
  const override = Array.isArray(row.reviewers);
  // ids a stale read still lists after a delete are ignored
  const effective = (override ? row.reviewers! : active).filter((id) => known.has(id));
  const names = effective.map((id) => reviewers.find((r) => r.id === id)!.name);
  // the first tick on a repo without an override makes one from the default set plus or minus that id
  const tick = (id: string, on: boolean) => onSave(on ? [...effective, id] : effective.filter((x) => x !== id));

  return (
    <PO.Root>
      <PO.Trigger asChild>
        <button type="button" className="rv-cell" aria-label={`Reviewers for ${slug}`}>
          {override ? (
            <>
              {names.length ? names.map((n) => <Chip key={n}>{n}</Chip>) : <span className="muted">override: none</span>}
              {names.length ? <span className="muted">override</span> : null}
            </>
          ) : (
            <span className="muted">{defaultText(names, row.path, botLabel)}</span>
          )}
        </button>
      </PO.Trigger>
      <PO.Portal>
        <PO.Content className="pop-c rv-pop" align="start" sideOffset={6} collisionPadding={8}>
          <ul>
            {reviewers.map((r) => {
              const h = hints(r, row.path);
              return (
                <li key={r.id}>
                  <label>
                    <input type="checkbox" checked={effective.includes(r.id)} disabled={disabled} onChange={(e) => tick(r.id, e.target.checked)} />
                    <span className={h.off ? 'rv-off' : undefined}>{r.name}</span>
                  </label>
                  {h.off ? <span className="rv-hint">{h.off}</span> : null}
                  {h.learn ? <span className="rv-hint">login learned from its first review</span> : null}
                </li>
              );
            })}
          </ul>
          <Button sm disabled={disabled || !override} onClick={() => onSave(null)}>Use default</Button>
        </PO.Content>
      </PO.Portal>
    </PO.Root>
  );
}
