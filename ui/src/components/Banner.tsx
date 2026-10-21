import type { ReactNode } from 'react';
import type { Tone } from '../lib/vocab';
import { Icon, type IconName } from './Icon';

/** Message strip. `top` renders it edge to edge above the top bar (offline, away). */
export function Banner({ tone = 'muted', icon, top, children, action, role }: { tone?: Tone; icon?: IconName; top?: boolean; children: ReactNode; action?: ReactNode; role?: 'status' | 'alert' }) {
  return (
    <div className={`banner t-${tone}${top ? ' top-banner' : ''}`} role={role ?? (tone === 'bad' ? 'alert' : 'status')}>
      {icon ? <Icon n={icon} /> : null}
      <div className="grow">{children}</div>
      {action}
    </div>
  );
}
