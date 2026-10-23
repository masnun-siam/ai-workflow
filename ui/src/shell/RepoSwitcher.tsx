import * as PO from '@radix-ui/react-popover';
import { Command } from 'cmdk';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '../components';
import { routes } from '../lib/routes';
import { RepoGroups } from './RepoSelect';
import { useRepo } from './useRepo';

const short = (slug: string) => slug.split('/').pop() ?? slug;

/** The repo picker: type to filter, repos grouped by owner, each shown by its repo name (several can share a project name). */
export function RepoSwitcher({ compact = false }: { compact?: boolean }) {
  const { repo, repos, current, setRepo } = useRepo();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const name = current?.name ?? (repo ? short(repo) : 'No repo');
  const pick = (go: () => void) => { setOpen(false); go(); };

  return (
    <PO.Root open={open} onOpenChange={setOpen}>
      <PO.Trigger asChild>
        {compact ? (
          <button type="button" className="repo-mark" style={{ width: 26, height: 26, fontSize: 12, border: 0, cursor: 'pointer' }} aria-label={`Repository: ${name}. Switch repository`}>
            {name[0]?.toUpperCase() ?? '?'}
          </button>
        ) : (
          <button type="button" className="repo-btn" aria-label={`Repository: ${name}. Switch repository`}>
            <span className="repo-mark" aria-hidden="true">{name[0]?.toUpperCase() ?? '?'}</span>
            <span className="grow" style={{ minWidth: 0 }}>
              <b className="ellipsis" style={{ display: 'block' }}>{name}</b>
              <span className="faint mono ellipsis" style={{ fontSize: 11.5, display: 'block' }}>{repo}</span>
            </span>
            <Icon n="down" s={14} />
          </button>
        )}
      </PO.Trigger>
      <PO.Portal>
        <PO.Content className="pop-c repo-pop" align="start" sideOffset={6} collisionPadding={8}>
          <Command label="Switch repository" filter={(v, q) => (v.toLowerCase().includes(q.toLowerCase()) ? 1 : 0)}>
            <Command.Input autoFocus placeholder={`Find a repository (${repos.length})…`} />
            <Command.List>
              <Command.Empty>No repository matches.</Command.Empty>
              <RepoGroups repos={repos} first={current} selected={repo} onPick={(slug) => pick(() => setRepo(slug))} />
            </Command.List>
          </Command>
          <button type="button" className="menu-i" style={{ borderTop: '1px solid var(--line)', borderRadius: 0, padding: '10px 14px' }} onClick={() => pick(() => navigate(routes.settings('repositories')))}>
            <Icon n="plus" />Add a repository
          </button>
        </PO.Content>
      </PO.Portal>
    </PO.Root>
  );
}
