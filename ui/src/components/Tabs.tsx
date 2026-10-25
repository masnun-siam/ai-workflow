import * as RT from '@radix-ui/react-tabs';
import { useEffect, type ReactNode } from 'react';
import { ignoreKey } from '../shell/shortcuts';

export interface TabDef {
  value: string;
  label: string;
  count?: number;
}

/** Radix tabs: `<Tabs value onValueChange tabs>` then one `<TabPanel value>` per tab as children. `pageKeys`: `[` / `]` step to the previous / next tab (FR-8), stopping at the ends. */
export function Tabs({ value, onValueChange, tabs, children, label, pageKeys }: { value: string; onValueChange: (v: string) => void; tabs: TabDef[]; children: ReactNode; label?: string; pageKeys?: boolean }) {
  useEffect(() => {
    if (!pageKeys) return;
    const h = (e: KeyboardEvent) => {
      if ((e.key !== '[' && e.key !== ']') || ignoreKey(e)) return;
      const next = tabs[tabs.findIndex((t) => t.value === value) + (e.key === ']' ? 1 : -1)];
      if (!next) return;
      e.preventDefault();
      onValueChange(next.value);
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [pageKeys, tabs, value, onValueChange]);
  return (
    <RT.Root value={value} onValueChange={onValueChange} className="stack" style={{ gap: 16 }}>
      <RT.List className="tabs-list" aria-label={label}>
        {tabs.map((t) => (
          <RT.Trigger key={t.value} value={t.value}>
            {t.label}
            {t.count != null ? <span className="n">{t.count}</span> : null}
          </RT.Trigger>
        ))}
      </RT.List>
      {children}
    </RT.Root>
  );
}

export const TabPanel = RT.Content;
