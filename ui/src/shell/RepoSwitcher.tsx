import * as PO from '@radix-ui/react-popover';
import { Command } from 'cmdk';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '../components';
import type { Repo } from '../api/types';
import { routes } from '../lib/routes';
import { useRepo } from './useRepo';

const owner = (slug: string) => slug.split('/')[0];
const short = (slug: string) => slug.split('/').pop() ?? slug;

/** The repo picker: type to filter, repos grouped by owner, each shown by its repo name (several can share a project name). */
export function RepoSwitcher({ compact = false }: { compact?: boolean }) {
  const { repo, repos, current, setRepo } = useRepo();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const name = current?.name ?? (repo ? short(repo) : 'No repo');
  const groups = new Map<string, Repo[]>();
  if (current) groups.set('Current', [current]);
  for (const r of [...repos].filter((x) => x !== current).sort((a, b) => a.slug.localeCompare(b.slug))) groups.set(owner(r.slug), [...(groups.get(owner(r.slug)) ?? []), r]);
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
              {[...groups].map(([o, rs]) => (
                <Command.Group key={o} heading={o}>
                  {rs.map((r) => (
                    <Command.Item key={r.slug} value={`${r.slug} ${r.name}`} onSelect={() => pick(() => setRepo(r.slug))}>
                      <span className="repo-mark" aria-hidden="true" style={{ width: 22, height: 22, fontSize: 11, borderRadius: 6 }}>{short(r.slug)[0]?.toUpperCase()}</span>
                      <span className="grow" style={{ minWidth: 0 }}>
                        <span className="ellipsis" style={{ display: 'block', fontWeight: 600 }}>{short(r.slug)}</span>
                        {r.name !== r.slug && r.name !== short(r.slug) ? <span className="faint ellipsis" style={{ display: 'block', fontSize: 12 }}>{r.name}</span> : null}
                      </span>
                      {r.slug === repo ? <Icon n="check" s={14} /> : null}
                    </Command.Item>
                  ))}
                </Command.Group>
              ))}
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
