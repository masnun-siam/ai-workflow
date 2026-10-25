import * as DM from '@radix-ui/react-dropdown-menu';
import type { ReactNode } from 'react';
import { useAction } from '../shell/shortcuts';
import { Button } from './Button';
import { Icon, type IconName } from './Icon';

export type MenuEntry =
  | { label: string; icon?: IconName; onSelect: () => void; danger?: boolean; disabled?: boolean; checked?: boolean }
  | 'sep';

/** Lists one menu item in the palette's "Actions here" while the menu is mounted (a hook per item, so one component per item). */
function MenuAction({ label, item }: { label: string; item: Exclude<MenuEntry, 'sep'> }) {
  useAction(item.disabled ? null : { label: label ? `${label} ${item.label}` : item.label, run: item.onSelect });
  return null;
}

/** Dropdown menu (Radix): arrow keys, type-ahead, Esc and focus return come for free. `trigger` must be a single focusable element. `paletteLabel` prefixes each item in the palette ("Resume on" → "Resume on personal"). */
export function Menu({ trigger, items, align = 'end', paletteLabel = '' }: { trigger: ReactNode; items: MenuEntry[]; align?: 'start' | 'end' | 'center'; paletteLabel?: string }) {
  return (
    <DM.Root>
      {items.map((it, i) => (it === 'sep' ? null : <MenuAction key={i} label={paletteLabel} item={it} />))}
      <DM.Trigger asChild>{trigger}</DM.Trigger>
      <DM.Portal>
        <DM.Content className="menu-c" align={align} sideOffset={6} collisionPadding={8}>
          {items.map((it, i) =>
            it === 'sep' ? (
              <DM.Separator key={i} className="menu-sep" />
            ) : (
              <DM.Item key={i} className={`menu-i${it.danger ? ' danger' : ''}`} disabled={it.disabled} onSelect={it.onSelect}>
                {it.icon ? <Icon n={it.icon} /> : null}
                <span className="grow ellipsis">{it.label}</span>
                {it.checked ? <Icon n="check" s={14} /> : null}
              </DM.Item>
            ),
          )}
        </DM.Content>
      </DM.Portal>
    </DM.Root>
  );
}

/** The ⋯ button with a menu: row actions, the feature page's More. */
export function MoreMenu({ items, label = 'More actions', sm = true }: { items: MenuEntry[]; label?: string; sm?: boolean }) {
  return <Menu items={items} trigger={<Button variant="ghost" icon sm={sm} aria-label={label}><Icon n="more" /></Button>} />;
}
