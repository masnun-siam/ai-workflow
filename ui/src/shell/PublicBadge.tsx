import * as PO from '@radix-ui/react-popover';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useShares } from '../api/hooks';
import { Chip, Icon } from '../components';
import { shortRepo } from '../lib/format';
import { routes } from '../lib/routes';

/** "Public (n)" while any share is live, on every page; the list links each live share to its PRD tab. */
export function PublicBadge() {
  const { data } = useShares();
  const [open, setOpen] = useState(false);
  const live = (Array.isArray(data) ? data : []).filter((s) => s.state === 'live');
  if (!live.length) return null;
  return (
    <PO.Root open={open} onOpenChange={setOpen}>
      <PO.Trigger asChild>
        <button type="button" className="btn sm" aria-label={`Public shares: ${live.length}`}>
          <Icon n="ext" s={14} />
          <span aria-hidden="true"><span className="hide-sm">Public </span>({live.length})</span>
        </button>
      </PO.Trigger>
      <PO.Portal>
        <PO.Content className="pop-c" align="end" sideOffset={6} collisionPadding={8} style={{ maxHeight: 320, overflow: 'auto', padding: 4 }}>
          {live.map((s) => (
            <Link key={s.id} className="menu-i" to={`${routes.feature(s.path.split('/').pop()!.replace(/\.md$/, ''), 'prd')}?repo=${s.repo}`} onClick={() => setOpen(false)} style={{ textDecoration: 'none', color: 'inherit' }}>
              <span className="grow ellipsis">{s.title}</span>
              <span className="faint mono" style={{ fontSize: 11.5 }}>{shortRepo(s.repo)}</span>
              {s.reachable === false ? <Chip tone="bad">not reachable</Chip> : null}
            </Link>
          ))}
        </PO.Content>
      </PO.Portal>
    </PO.Root>
  );
}
