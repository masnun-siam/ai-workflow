import * as RT from '@radix-ui/react-tabs';
import type { ReactNode } from 'react';

export interface TabDef {
  value: string;
  label: string;
  count?: number;
}

/** Radix tabs: `<Tabs value onValueChange tabs>` then one `<TabPanel value>` per tab as children. */
export function Tabs({ value, onValueChange, tabs, children, label }: { value: string; onValueChange: (v: string) => void; tabs: TabDef[]; children: ReactNode; label?: string }) {
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
