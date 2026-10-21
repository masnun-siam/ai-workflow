import type { ReactNode } from 'react';
import type { SessionStatus } from '../api/types';
import { ISSUE, SESS, type IssueStatus, type Tone } from '../lib/vocab';
import { Icon } from './Icon';

/** The pill. Status is always text as well as colour (FR-32). */
export function Chip({ tone = 'muted', live, children, title }: { tone?: Tone; live?: boolean; children: ReactNode; title?: string }) {
  return (
    <span className={`chip t-${tone}${live ? ' live' : ''}`} title={title}>
      {live ? <span className="dot" /> : null}
      {children}
    </span>
  );
}

export const StatusChip = Chip;

export const IssueChip = ({ s }: { s: IssueStatus }) => <Chip tone={ISSUE[s].tone}>{ISSUE[s].label}</Chip>;

export function SessionChip({ s }: { s: SessionStatus }) {
  const v = SESS[s] ?? { label: String(s), tone: 'muted' as Tone };
  return <Chip tone={v.tone} live={'live' in v && v.live}>{v.label}</Chip>;
}

export function CiChip({ ci }: { ci: string | null | undefined }) {
  if (ci === 'success') return <Chip tone="ship"><Icon n="check" s={12} />CI passed</Chip>;
  if (ci === 'failure') return <Chip tone="bad"><Icon n="x" s={12} />CI failed</Chip>;
  if (ci === 'pending') return <Chip tone="review" live>CI running</Chip>;
  return null;
}
