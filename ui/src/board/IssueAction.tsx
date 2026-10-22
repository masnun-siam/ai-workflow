// The one row action per issue (FR-13), shared by the Board cards, the Feature Issues tab and the issue panel.
import { useNavigate } from 'react-router-dom';
import { useCleanupIssue, useSettings, useSkipCi } from '../api/hooks';
import type { DeliveryCard } from '../api/types';
import { Button, Chip, Icon, Menu, toast, useConfirm } from '../components';
import { issueStatus } from '../lib/vocab';
import { routes } from '../lib/routes';
import { usePanel } from '../panels/PanelContext';
import { useRepo } from '../shell/useRepo';
import { useStarter } from './actions';
import { ResolveConflicts } from './ResolveConflicts';

export type IssueActionKind = 'refine' | 'blocked' | 'queued' | 'start' | 'answer' | 'watch' | 'merge' | 'grind' | 'openPr' | 'skipCi' | 'round' | 'resolve' | 'cleanup' | 'none';

/** Which action a card gets. Pure so the board and tests agree. */
export function actionKind(card: DeliveryCard): IssueActionKind {
  const st = issueStatus(card);
  const s = card.session;
  if (st === 'unrefined') return 'refine';
  if (st === 'blocked') return 'blocked';
  if (st === 'ready') return s?.status === 'queued' ? 'queued' : 'start';
  if (st === 'in_progress' || st === 'draft_pr') {
    if (s?.status === 'waiting') return 'answer';
    if (s) return 'watch';
    return card.pr ? 'openPr' : 'none';
  }
  if (card.pr?.conflict && st !== 'merged') return 'resolve';
  if (st === 'in_review') return card.mergeable ? 'merge' : card.grind_on && !card.grind && card.pr && !card.pr.draft ? 'grind' : 'openPr';
  if (st === 'grinding') return card.grind?.state === 'paused' ? 'skipCi' : 'round';
  if (st === 'merged' && card.needs_cleanup) return 'cleanup';
  return 'none';
}

export function IssueAction({ card, repo }: { card: DeliveryCard; repo: string }) {
  const starter = useStarter();
  const panel = usePanel();
  const navigate = useNavigate();
  const { link } = useRepo();
  const confirm = useConfirm();
  const skip = useSkipCi();
  const clean = useCleanupIssue();
  const accounts = useSettings().data;
  const kind = actionKind(card);
  const n = card.n;
  const stop = (e: { stopPropagation: () => void }) => e.stopPropagation();

  const start = () => starter.startBoard({ repo, skill: 'implement-issue', arg: String(n), via: 'headless' });
  const onAccount = (label: string) => starter.startSession({ repo, command: 'implement-issue', args: String(n), issue: n, claude_cmd: label });
  const openPr = () => card.pr && panel.open({ kind: 'pr', repo, n: card.pr.n });

  let el: React.ReactNode = null;
  switch (kind) {
    case 'refine':
      el = <Button sm disabled={starter.pending} onClick={() => starter.startBoard({ repo, skill: 'refine-issues', arg: String(n), via: 'headless' })}>Refine</Button>;
      break;
    case 'blocked':
      el = <span className="muted" style={{ fontSize: 13 }}><Icon n="lock" s={13} /> after {card.blocked_by.map((b) => `#${b}`).join(', ')}</span>;
      break;
    case 'queued':
      el = <Chip>Queued</Chip>;
      break;
    case 'start': {
      const others = (accounts?.commands ?? []).filter((c) => c.label !== accounts?.default);
      el = (
        <span className="split">
          <Button sm variant="primary" disabled={starter.pending} onClick={() => start()}>{card.last_failed ? 'Retry' : 'Start'}</Button>
          <Menu
            trigger={<Button sm variant="primary" aria-label="More ways to start"><Icon n="down" s={13} /></Button>}
            items={[
              { label: 'Start here (tracked)', icon: 'play', onSelect: () => void start() },
              ...others.map((c) => ({ label: `Start on ${c.label}`, icon: 'user' as const, onSelect: () => void onAccount(c.label) })),
              ...(others.length === 0 ? [{ label: 'Start on another account', icon: 'user' as const, disabled: true, onSelect: () => {} }] : []),
            ]}
          />
        </span>
      );
      break;
    }
    case 'answer':
      el = <Button sm variant="you" onClick={() => card.session && navigate(link(routes.session(card.session.id)))}>Answer</Button>;
      break;
    case 'watch':
      el = <Button sm onClick={() => card.session && navigate(link(routes.session(card.session.id)))}>Watch</Button>;
      break;
    case 'merge':
      el = <Button sm variant="primary" onClick={openPr}>Merge</Button>;
      break;
    case 'grind':
      el = <Button sm disabled={starter.pending} onClick={() => card.pr && starter.startBoard({ repo, skill: 'pr-grind', arg: card.pr.url, via: 'headless' })}>Grind</Button>;
      break;
    case 'openPr':
      el = <Button sm onClick={openPr}>Open PR</Button>;
      break;
    case 'skipCi':
      el = <Button sm disabled={skip.isPending} onClick={() => card.pr && skip.mutate({ repo, pr: card.pr.n }, { onSuccess: () => toast('Skipping CI and continuing the grind') })}>Skip CI</Button>;
      break;
    case 'resolve':
      el = card.pr ? <ResolveConflicts repo={repo} url={card.pr.url} n={card.pr.n} primary /> : null;
      break;
    case 'round':
      el = <span className="muted" style={{ fontSize: 13 }}>round {card.grind?.round ?? 1}</span>;
      break;
    case 'cleanup':
      el = (
        <Button
          sm
          disabled={clean.isPending}
          onClick={async () => {
            const nc = card.needs_cleanup;
            const ok = await confirm({
              title: `Clean up #${n}?`,
              okLabel: 'Clean up',
              danger: true,
              body: (
                <div className="stack">
                  <p>Removes its worktree and branch. This will be lost:</p>
                  <p><b>Uncommitted files</b></p>
                  {nc?.uncommitted.length ? <ul>{nc.uncommitted.map((f) => <li key={f} className="mono">{f}</li>)}</ul> : <p className="muted">None</p>}
                  <p><b>Unpushed commits</b></p>
                  {nc?.unpushed.length ? <ul>{nc.unpushed.map((f) => <li key={f} className="mono">{f}</li>)}</ul> : <p className="muted">None</p>}
                </div>
              ),
            });
            if (ok) clean.mutate({ repo, issue: n }, { onSuccess: () => toast(`Cleaned up #${n}`) });
          }}
        >
          Clean up
        </Button>
      );
      break;
  }
  return <span onClick={stop} onKeyDown={stop}>{el}</span>;
}
