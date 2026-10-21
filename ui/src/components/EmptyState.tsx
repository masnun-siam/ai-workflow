import type { ReactNode } from 'react';
import { Icon, type IconName } from './Icon';

/** Says what happened and what to do (FR-30). Children are the actions. */
export function EmptyState({ icon, title, children, actions }: { icon?: IconName; title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="empty">
      {icon ? <Icon n={icon} s={22} /> : null}
      <h2>{title}</h2>
      {children ? <div className="muted">{children}</div> : null}
      {actions ? <div className="row wrap">{actions}</div> : null}
    </div>
  );
}
