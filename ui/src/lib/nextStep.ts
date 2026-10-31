// FR-12: the Next step box on a feature page. Pure: Feature in, one primary action (and at most one secondary) out.
import type { ActionKey } from '../shell/shortcuts';
import { countBy, type Feature } from './features';

export type FeatureTab = 'issues' | 'prd' | 'review' | 'sessions';
export type StepAction =
  | { kind: 'startReview' }
  | { kind: 'approve' }
  | { kind: 'tab'; tab: FeatureTab }
  | { kind: 'createTasks' }
  | { kind: 'refine'; issues: number[] }
  | { kind: 'merge'; pr: number }
  | { kind: 'dispatch' }
  | { kind: 'openDispatch'; id: string }
  | { kind: 'closeEpic' };

/** FR-4: the key of a next-step action; the Features list shares it. */
export const stepKey = (a: StepAction): ActionKey | undefined => (a.kind === 'approve' ? 'p' : a.kind === 'refine' ? 'e' : a.kind === 'merge' ? 'm' : undefined);

export interface Step {
  title: string;
  hint: string;
  primary: { label: string; action: StepAction };
  secondary?: { label: string; action: StepAction };
  quiet?: boolean; // informational: nothing needs the user
}

/** Who has the next move on a feature: a dispatch stopped on you, a step that waits for your go, or nothing asked of you. */
export type Attention = 'you' | 'go' | 'auto';
export const attention = (s: Step, running?: { you: number } | null): Attention => (running?.you ? 'you' : s.quiet ? 'auto' : 'go');

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;

/** `running`: the epic's live dispatch, when there is one; it replaces the build-stage advice. */
export function nextStep(f: Feature, running?: { id: string; closed: number; total: number; you: number } | null): Step {
  const c = countBy(f.issues);
  switch (f.stage) {
    case 'draft':
      return {
        title: 'Get the PRD reviewed',
        hint: 'Run the lens panel on the draft before you approve it.',
        primary: { label: 'Start peer review', action: { kind: 'startReview' } },
        secondary: { label: 'Approve without review', action: { kind: 'approve' } },
      };
    case 'review': {
      const p = f.panel;
      const max = p?.max_rounds ?? 0;
      if (p?.state === 'cap reached' || (p && max > 0 && p.round >= max && p.state !== 'approved' && p.state !== 'running')) {
        return {
          title: 'Review stopped at the round limit',
          hint: p?.reason || 'Some lenses still ask for changes.',
          primary: { label: 'Decide', action: { kind: 'tab', tab: 'review' } },
          secondary: { label: 'Approve anyway', action: { kind: 'approve' } },
        };
      }
      if (p?.state === 'approved' || !p) {
        return {
          title: p ? 'Every lens approves' : 'Ready to approve',
          hint: 'Approving files the epic and unlocks tasks.',
          primary: { label: 'Approve PRD', action: { kind: 'approve' } },
        };
      }
      const total = p.total;
      return {
        title: `Peer review round ${p.round} of ${max || '?'} is running`,
        hint: `${p.approved} of ${total} lenses approve. You hear from it only if it needs you.`,
        primary: { label: 'Watch review', action: { kind: 'tab', tab: 'review' } },
        secondary: { label: 'Approve now', action: { kind: 'approve' } },
        quiet: true,
      };
    }
    case 'approved':
      return {
        title: 'Break it into tasks',
        hint: `Creates small one-PR issues under the epic${f.epic ? ` #${f.epic}` : ''}, with dependencies.`,
        primary: { label: 'Create tasks', action: { kind: 'createTasks' } },
      };
    case 'tasks': {
      const un = f.issues.filter((i) => i.status === 'unrefined' || (i.column === 'unrefined')).map((i) => i.n);
      const ids = un.length ? un : f.prd.unrefined;
      return {
        title: `${plural(ids.length, 'issue')} need${ids.length === 1 ? 's' : ''} refinement`,
        hint: 'Refining writes WHAT, WHY and HOW so each issue can be built without guessing.',
        primary: { label: `Refine ${ids.length}`, action: { kind: 'refine', issues: ids } },
      };
    }
    case 'building': {
      const m = f.issues.find((i) => i.mergeable);
      const ready = f.issues.filter((i) => i.status === 'ready').map((i) => i.n);
      if (running) {
        return {
          title: running.you ? `The dispatch needs you on ${plural(running.you, 'issue')}` : 'The dispatch is building this',
          hint: `${running.closed} of ${running.total} issues done.`,
          primary: { label: 'Open dispatch', action: { kind: 'openDispatch', id: running.id } },
          quiet: !running.you,
        };
      }
      if (m && m.pr) {
        return {
          title: 'A PR is ready to merge',
          hint: `#${m.n} ${m.title}: checks green and reviewed.`,
          primary: { label: 'Review and merge', action: { kind: 'merge', pr: m.pr.n } },
        };
      }
      if (ready.length) {
        return f.epic
          ? {
              title: `${plural(ready.length, 'issue')} ready to build`,
              hint: 'Run the epic: its issues build side by side, then grind, merge and wrap up as what they wait for is done.',
              primary: { label: 'Run epic', action: { kind: 'dispatch' } },
            }
          : {
              title: `${plural(ready.length, 'issue')} ready to build`,
              hint: 'With no open epic to run, start them one at a time from the Issues tab.',
              primary: { label: 'See the issues', action: { kind: 'tab', tab: 'issues' } },
            };
      }
      return {
        title: 'Building',
        hint: `${c.merged ?? 0} of ${f.issues.length} merged.`,
        primary: { label: 'See the issues', action: { kind: 'tab', tab: 'issues' } },
        quiet: true,
      };
    }
    case 'shipped':
      if (!f.epic)
        return {
          title: 'Shipped',
          hint: 'Everything merged and the epic is closed.',
          primary: { label: 'See the issues', action: { kind: 'tab', tab: 'issues' } },
          quiet: true,
        };
      return {
        title: 'Everything merged',
        hint: 'Close the epic to tidy GitHub. Its issues are already closed.',
        primary: { label: 'Close epic', action: { kind: 'closeEpic' } },
      };
  }
}
