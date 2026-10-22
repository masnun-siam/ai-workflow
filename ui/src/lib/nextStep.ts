// FR-12: the Next step box on a feature page. Pure: Feature in, one primary action (and at most one secondary) out.
import { countBy, type Feature } from './features';

export type FeatureTab = 'issues' | 'prd' | 'review' | 'sessions';
export type StepAction =
  | { kind: 'startReview' }
  | { kind: 'approve' }
  | { kind: 'tab'; tab: FeatureTab }
  | { kind: 'createTasks' }
  | { kind: 'refine'; issues: number[] }
  | { kind: 'startReady'; issues: number[] }
  | { kind: 'merge'; pr: number }
  | { kind: 'toggleAuto' }
  | { kind: 'board' }
  | { kind: 'closeEpic' };

export interface Step {
  title: string;
  hint: string;
  primary: { label: string; action: StepAction };
  secondary?: { label: string; action: StepAction };
  quiet?: boolean; // informational: nothing needs the user
}

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;

export function nextStep(f: Feature): Step {
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
      const ready = f.issues.filter((i) => i.status === 'ready').map((i) => i.n);
      return {
        title: `${plural(ids.length, 'issue')} need${ids.length === 1 ? 's' : ''} refinement`,
        hint: 'Refining writes WHAT, WHY and HOW so each issue can be built without guessing.',
        primary: { label: `Refine ${ids.length}`, action: { kind: 'refine', issues: ids } },
        secondary: ready.length ? { label: `Start ${ready.length} ready`, action: { kind: 'startReady', issues: ready } } : undefined,
      };
    }
    case 'building': {
      const m = f.issues.find((i) => i.mergeable);
      const ready = f.issues.filter((i) => i.status === 'ready').map((i) => i.n);
      if (m && m.pr) {
        return {
          title: 'A PR is ready to merge',
          hint: `#${m.n} ${m.title}: checks green and reviewed.`,
          primary: { label: 'Review and merge', action: { kind: 'merge', pr: m.pr.n } },
          secondary: f.autobuild || !f.epic ? undefined : { label: 'Turn on auto-build', action: { kind: 'toggleAuto' } },
        };
      }
      if (!f.epic && ready.length) {
        // auto-build runs per epic lane; without an open epic, starting by hand is the only way
        return {
          title: `${plural(ready.length, 'issue')} ready to build`,
          hint: 'Start them yourself.',
          primary: { label: `Start ${ready.length} now`, action: { kind: 'startReady', issues: ready } },
        };
      }
      if (!f.autobuild && ready.length) {
        return {
          title: `${plural(ready.length, 'issue')} ready to build`,
          hint: 'Start them yourself, or turn on auto-build to start them as slots free up.',
          primary: { label: 'Turn on auto-build', action: { kind: 'toggleAuto' } },
          secondary: { label: `Start ${ready.length} now`, action: { kind: 'startReady', issues: ready } },
        };
      }
      return {
        title: 'Building',
        hint: `${c.merged ?? 0} of ${f.issues.length} merged. Auto-build is ${f.autobuild ? 'on' : 'off'}.`,
        primary: { label: 'Open board', action: { kind: 'board' } },
        quiet: true,
      };
    }
    case 'shipped':
      return {
        title: 'Everything merged',
        hint: 'Close the epic to tidy GitHub. Its issues are already closed.',
        primary: { label: 'Close epic', action: { kind: 'closeEpic' } },
      };
  }
}
