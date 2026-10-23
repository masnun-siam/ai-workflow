import * as PO from '@radix-ui/react-popover';
import { Command } from 'cmdk';
import { useState } from 'react';
import { Icon } from '../components';
import type { Repo } from '../api/types';

const owner = (slug: string) => slug.split('/')[0];
const short = (slug: string) => slug.split('/').pop() ?? slug;

/** Repos grouped by owner (an optional `first` repo goes under "Current"), each shown by its repo name. */
export function RepoGroups({ repos, first, selected, onPick }: { repos: Repo[]; first?: Repo; selected?: string; onPick: (slug: string) => void }) {
  const groups = new Map<string, Repo[]>();
  if (first) groups.set('Current', [first]);
  for (const r of repos.filter((x) => x !== first).sort((a, b) => a.slug.localeCompare(b.slug))) groups.set(owner(r.slug), [...(groups.get(owner(r.slug)) ?? []), r]);
  return (
    <>
      {[...groups].map(([o, rs]) => (
        <Command.Group key={o} heading={o}>
          {rs.map((r) => (
            <Command.Item key={r.slug} value={`${r.slug} ${r.name}`} onSelect={() => onPick(r.slug)}>
              <span className="repo-mark" aria-hidden="true" style={{ width: 22, height: 22, fontSize: 11, borderRadius: 6 }}>{short(r.slug)[0]?.toUpperCase()}</span>
              <span className="grow" style={{ minWidth: 0 }}>
                <span className="ellipsis" style={{ display: 'block', fontWeight: 600 }}>{short(r.slug)}</span>
                {r.name !== r.slug && r.name !== short(r.slug) ? <span className="faint ellipsis" style={{ display: 'block', fontSize: 12 }}>{r.name}</span> : null}
              </span>
              {r.slug === selected ? <Icon n="check" s={14} /> : null}
            </Command.Item>
          ))}
        </Command.Group>
      ))}
    </>
  );
}

export type Extra = { value: string; label: string };

/** The same searchable repo picker as the top-bar switcher, as a form field. `extras` are fixed rows around the repos ("All repos", "Another folder…"). */
export function RepoSelect({ repos, value, onChange, extrasBefore = [], extrasAfter = [], label, id, width }: {
  repos: Repo[];
  value: string;
  onChange: (v: string) => void;
  extrasBefore?: Extra[];
  extrasAfter?: Extra[];
  label: string;
  id?: string;
  width?: number | string;
}) {
  const [open, setOpen] = useState(false);
  const extras = [...extrasBefore, ...extrasAfter];
  const shown = extras.find((e) => e.value === value)?.label ?? (value ? short(value) : 'Pick a repository');
  const pick = (v: string) => { setOpen(false); onChange(v); };
  const rows = (xs: Extra[]) => xs.map((e) => (
    <Command.Item key={e.value} value={e.label} onSelect={() => pick(e.value)}>
      <span className="grow">{e.label}</span>
      {e.value === value ? <Icon n="check" s={14} /> : null}
    </Command.Item>
  ));
  return (
    <PO.Root open={open} onOpenChange={setOpen}>
      <PO.Trigger asChild>
        <button type="button" id={id} className="f row" style={{ width, textAlign: 'left', cursor: 'pointer' }} aria-label={`${label}: ${shown}`}>
          <span className="grow ellipsis">{shown}</span>
          <Icon n="down" s={14} />
        </button>
      </PO.Trigger>
      <PO.Portal>
        <PO.Content className="pop-c repo-pop" align="start" sideOffset={6} collisionPadding={8}>
          <Command label={label} filter={(v, q) => (v.toLowerCase().includes(q.toLowerCase()) ? 1 : 0)}>
            <Command.Input autoFocus placeholder={`Find a repository (${repos.length})…`} />
            <Command.List>
              <Command.Empty>No repository matches.</Command.Empty>
              {rows(extrasBefore)}
              <RepoGroups repos={repos} selected={value} onPick={pick} />
              {rows(extrasAfter)}
            </Command.List>
          </Command>
        </PO.Content>
      </PO.Portal>
    </PO.Root>
  );
}
