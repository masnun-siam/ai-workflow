import * as PO from '@radix-ui/react-popover';
import { Command } from 'cmdk';
import { useState } from 'react';
import { useBranches } from '../api/hooks';
import { Icon } from '../components';

const BASE = 'Repo’s base';

/** A searchable list of the repo's existing branches (no free text). null = the repo's base. Disabled until the dialog knows its repo. */
export function BranchSelect({ id, repo, value, onChange }: { id: string; repo: string | null; value: string | null; onChange: (v: string | null) => void }) {
  const [open, setOpen] = useState(false);
  const q = useBranches(repo);
  const shown = value ?? (q.isLoading ? 'Loading branches…' : BASE);
  const pick = (v: string | null) => { setOpen(false); onChange(v); };
  return (
    <>
      <PO.Root open={open} onOpenChange={setOpen}>
        <PO.Trigger asChild>
          <button type="button" id={id} className="f row" style={{ textAlign: 'left', cursor: 'pointer' }} disabled={!repo} aria-label={`Base branch: ${shown}`}>
            <span className="grow ellipsis">{shown}</span>
            <Icon n="down" s={14} />
          </button>
        </PO.Trigger>
        <PO.Portal>
          <PO.Content className="pop-c repo-pop" align="start" sideOffset={6} collisionPadding={8}>
            <Command label="Base branch" filter={(v, s) => (v.toLowerCase().includes(s.toLowerCase()) ? 1 : 0)}>
              <Command.Input autoFocus placeholder="Find a branch…" />
              <Command.List>
                <Command.Empty>No branch matches.</Command.Empty>
                <Command.Item value={`${BASE} (default)`} onSelect={() => pick(null)}>
                  <span className="grow">{BASE} (default)</span>
                  {value === null ? <Icon n="check" s={14} /> : null}
                </Command.Item>
                {(q.data?.branches ?? []).map((b) => (
                  <Command.Item key={b} value={b} onSelect={() => pick(b)}>
                    <span className="grow ellipsis">{b}</span>
                    {b === q.data?.default ? <span className="faint">default</span> : null}
                    {b === value ? <Icon n="check" s={14} /> : null}
                  </Command.Item>
                ))}
              </Command.List>
            </Command>
          </PO.Content>
        </PO.Portal>
      </PO.Root>
      {q.isError ? <span className="hint" style={{ color: 'var(--bad)' }}>{q.error.message}</span> : null}
    </>
  );
}
