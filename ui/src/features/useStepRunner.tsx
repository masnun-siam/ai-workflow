// Runs a Next-step action (lib/nextStep.ts StepAction) for a feature: the same wiring on the list rows and the feature page.
import { useNavigate } from 'react-router-dom';
import { useCloseEpic } from '../api/hooks';
import { toast, useConfirm } from '../components';
import { useRefining, useStarter } from '../board/actions';
import type { Feature } from '../lib/features';
import type { StepAction } from '../lib/nextStep';
import { routes } from '../lib/routes';
import { usePanel } from '../panels/PanelContext';
import { repoLink } from '../lib/repo';
import { PLAN_RUN } from '../lib/vocab';
import { approveArgs } from '../inbox/items';

export const taskArg = (epic: number, path: string, text: string) =>
  `A finding for epic #${epic} (PRD ${path}): ${text.trim().replace(/\s+/g, ' ')}`;

export function useStepRunner(f: Feature, repo: string) {
  const navigate = useNavigate();
  const link = (path: string) => repoLink(repo, path);
  const confirm = useConfirm();
  const starter = useStarter();
  const refining = useRefining(repo);
  const panel = usePanel();
  const close = useCloseEpic();
  const go = (tab?: string) => navigate(link(routes.feature(f.slug, tab)));

  const run = async (a: StepAction) => {
    switch (a.kind) {
      case 'startReview':
        return go('review');
      case 'tab':
        return go(a.tab);
      case 'openDispatch':
        return navigate(link(routes.dispatch(a.id)));
      case 'approve': {
        const ok = await confirm({
          title: 'Approve this PRD?',
          okLabel: 'Approve PRD',
          body: <p>Runs <code>/create-prd</code> to fold in the review, set the PRD to Approved and file its epic. It then commits the PRD and opens a PR (merged right away on repos you own). Claude may ask you questions.</p>,
        });
        if (ok) await starter.startSession({ repo, command: 'create-prd', args: approveArgs(f.prd.path), ...PLAN_RUN });
        return;
      }
      case 'createTasks':
        await starter.startBoard({ repo, skill: 'create-tasks', arg: f.prd.path, via: 'headless', ...(f.epic ? { issue: f.epic } : {}), ...PLAN_RUN });
        return;
      case 'refine': {
        const live = a.issues.map((n) => refining.get(n)).find(Boolean);
        if (live && a.issues.every((n) => refining.has(n))) return navigate(link(routes.session(live)));
        await starter.startBoard({ repo, skill: 'refine-issues', arg: a.issues.filter((n) => !refining.has(n)).join(' '), via: 'headless', ...(f.epic ? { issue: f.epic } : {}), ...PLAN_RUN });
        return;
      }
      case 'merge':
        panel.open({ kind: 'pr', repo, n: a.pr });
        return;
      case 'dispatch':
        if (f.epic) navigate(link(routes.newDispatch(`${repo}#${f.epic}`)));
        return;
      case 'closeEpic': {
        if (!f.epic) return;
        const open = f.issues.filter((i) => i.status !== 'merged').length;
        const ok = await confirm({
          title: `Close epic #${f.epic}?`,
          okLabel: 'Close epic',
          danger: true,
          body: <p>Closes the epic and its {open} open child issue{open === 1 ? '' : 's'} as completed.</p>,
        });
        if (ok) close.mutate({ repo, epic: f.epic }, { onSuccess: () => toast(`Closed epic #${f.epic}`) });
      }
    }
  };
  /** A refine step whose every issue has a live session says so; clicking it opens that session. */
  const labelOf = (a: StepAction, label: string) => (a.kind === 'refine' && a.issues.length && a.issues.every((n) => refining.has(n)) ? 'Refining…' : label);
  return { run, labelOf, busy: starter.pending || close.isPending };
}
