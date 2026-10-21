// One Inbox row per item type (FR-7, FR-8): icon, title, meta, detail and its inline actions.
import { useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useCleanupIssue, useResume, useReviewRounds, useSettings, useSkipCi, useStartNow, useStartSession, useStop, useStopGrind } from '../api/hooks';
import type { InboxItem, Question } from '../api/types';
import { Button, LinkButton, Menu, useConfirm, useToast, type IconName } from '../components';
import { agoIso, clockText, shortRepo } from '../lib/format';
import { routes } from '../lib/routes';
import { type Tone } from '../lib/vocab';
import { usePanel } from '../panels/PanelContext';
import { copyCommand, useTerminal } from '../session/terminal';
import { useStartError } from '../session/useSessionActions';
import { QuestionForm } from '../questions/QuestionForm';
import { Icon } from '../components';

export const approveArgs = (path: string) =>
  `${path} approve: the team has reviewed this PRD. Fold in the review's changes, set the status to Approved and file the epic.`;
const slugOfPrd = (p: string) => p.replace(/^.*\//, '').replace(/\.md$/, '');
const cmdName = (c?: string) => (c ?? '').replace(/^\/(?:[\w-]+:)?/, '').trim() || 'session';
const featureLink = (it: { repo: string | null; prd_path: string }, tab: string) =>
  `${routes.feature(slugOfPrd(it.prd_path), tab)}${it.repo ? `?repo=${it.repo}` : ''}`;
const questionsOf = (qs: unknown): Question[] => (Array.isArray(qs) ? qs : ((qs as { questions?: Question[] } | null)?.questions ?? []));

/** Every inline action in one hook; rows get the functions, so there is one set of mutations per page. */
export function useInboxActions() {
  const confirm = useConfirm();
  const toast = useToast();
  const nav = useNavigate();
  const panel = usePanel();
  const qc = useQueryClient();
  const terminal = useTerminal();
  const start = useStartSession();
  const rounds = useReviewRounds();
  const skip = useSkipCi();
  const stopGrind = useStopGrind();
  const resume = useResume();
  const stop = useStop();
  const startNowM = useStartNow();
  const startErr = useStartError();
  const cleanup = useCleanupIssue();
  const goSession = (id?: string) => id && nav(routes.session(id));
  return {
    terminal,
    panel,
    recheck: () => qc.invalidateQueries({ queryKey: ['inbox'] }),
    copy: copyCommand,
    approve: async (repo: string, path: string) => {
      const ok = await confirm({
        title: 'Approve this PRD?',
        body: 'This runs /create-prd to fold in the review, set the PRD to Approved and file its epic on GitHub.',
        okLabel: 'Approve PRD',
      });
      if (ok) start.mutate({ repo, command: 'create-prd', args: approveArgs(path) }, { onSuccess: (s) => goSession(s.id) });
    },
    moreRounds: (panelId: string) => rounds.mutate({ panel: panelId, add: 2 }, { onSuccess: () => toast('Two more review rounds started') }),
    skipCi: async (repo: string, pr: number) => {
      if (await confirm({ title: `Skip CI on PR #${pr}?`, body: 'The grind continues with its review rounds and ignores the failing or pending checks.', okLabel: 'Skip CI and continue' }))
        skip.mutate({ repo, pr }, { onSuccess: () => toast('Grind continues') });
    },
    stopGrind: async (repo: string, pr: number) => {
      if (await confirm({ title: `Stop the grind on PR #${pr}?`, body: 'The loop ends. The PR stays open and you can start a grind again later.', okLabel: 'Stop grind', danger: true }))
        stopGrind.mutate({ repo, pr }, { onSuccess: () => toast('Grind stopped') });
    },
    retry: (id: string) => resume.mutate({ id }, { onSuccess: (s) => goSession(s.id ?? id), onError: startErr }),
    resumeOn: (id: string, claude_cmd: string) => resume.mutate({ id, claude_cmd }, { onSuccess: () => toast('Resuming on the other account'), onError: startErr }),
    startNow: (id: string) => startNowM.mutate(id, { onSuccess: (s) => goSession(s.id) }),
    cancel: async (id: string) => {
      if (await confirm({ title: 'Cancel this queued session?', body: 'It never started, so nothing is lost.', okLabel: 'Cancel it', cancelLabel: 'Keep it', danger: true })) stop.mutate(id);
    },
    cleanup: async (repo: string, issue: number, uncommitted: string[], unpushed: string[]) => {
      const ok = await confirm({
        title: `Remove the worktree for #${issue}?`,
        okLabel: 'Remove worktree',
        danger: true,
        body: (
          <div className="stack" style={{ gap: 8 }}>
            <p>This deletes the local worktree. The work below is not saved on GitHub and will be lost.</p>
            {uncommitted.length ? <><b>Uncommitted files ({uncommitted.length})</b><ul className="mono" style={{ margin: 0, paddingLeft: 18 }}>{uncommitted.map((f) => <li key={f}>{f}</li>)}</ul></> : null}
            {unpushed.length ? <><b>Unpushed commits ({unpushed.length})</b><ul className="mono" style={{ margin: 0, paddingLeft: 18 }}>{unpushed.map((f) => <li key={f}>{f}</li>)}</ul></> : null}
          </div>
        ),
      });
      if (ok) cleanup.mutate({ repo, issue }, { onSuccess: () => toast('Worktree removed') });
    },
  };
}
export type InboxActions = ReturnType<typeof useInboxActions>;

interface Props {
  item: InboxItem;
  a: InboxActions;
  open: boolean;
  toggle: () => void;
  publish: (slug: string) => void;
}

export function ItemRow({ item, a, open, toggle, publish }: Props) {
  const settings = useSettings();
  const repo = item.repo ?? '';
  const where = item.repo ? shortRepo(item.repo) : 'All repos';
  const at = typeof item.at === 'string' ? agoIso(item.at) : '';
  let icon: IconName = 'alert';
  let tone: Tone = 'muted';
  let title = '';
  let meta: (string | undefined | false)[] = [where];
  let detail: string | undefined;
  let acts: React.ReactNode = null;
  let body: React.ReactNode = null;
  const sess = (id: string) => (
    <LinkButton sm variant="ghost" to={routes.session(id)}>Open session</LinkButton>
  );
  const prdTitle = (p: string) => slugOfPrd(p).replace(/-/g, ' ');

  switch (item.type) {
    case 'gh_auth':
      icon = 'github'; tone = 'bad'; title = 'GitHub CLI is not signed in'; meta = ['All repos'];
      detail = item.error || 'Boards, issue actions and merges are paused until gh can reach GitHub.';
      acts = (<><Button sm variant="primary" onClick={() => void a.copy('gh auth login')}>Copy fix command</Button><Button sm onClick={() => void a.recheck()}>Check again</Button></>);
      break;
    case 'question': {
      const qs = questionsOf(item.questions);
      icon = 'msg'; tone = 'you';
      title = qs.length > 1 ? `${qs.length} questions from ${cmdName(item.command)}` : (qs[0]?.question ?? `A question from ${cmdName(item.command)}`);
      meta = [where, item.command ? cmdName(item.command) : undefined, at && `asked ${at} ago`];
      acts = (<>{sess(item.session_id)}<Button sm variant={open ? 'default' : 'you'} aria-expanded={open} onClick={toggle}>{open ? 'Hide' : 'Answer'}</Button></>);
      body = open ? <QuestionForm sessionId={item.session_id} /> : null;
      break;
    }
    case 'review_cap':
      icon = 'eye'; tone = 'plan'; title = `Peer review hit the round limit on “${prdTitle(item.prd_path)}”`;
      meta = [where, `round ${item.round} of ${item.max_rounds}`]; detail = item.note ?? undefined;
      acts = (<>
        <Button sm onClick={() => void a.approve(repo, item.prd_path)}>Approve PRD anyway</Button>
        <Button sm onClick={() => a.moreRounds(item.panel)}>Run 2 more rounds</Button>
        <LinkButton sm variant="primary" to={featureLink(item, 'review')}>Open review</LinkButton>
      </>);
      break;
    case 'review_approved':
      icon = 'check'; tone = 'plan'; title = `Every lens approves “${prdTitle(item.prd_path)}”`;
      detail = 'Approving sets the PRD to Approved and files its epic on GitHub.';
      acts = (<><Button sm variant="primary" onClick={() => void a.approve(repo, item.prd_path)}>Approve PRD</Button><LinkButton sm to={featureLink(item, 'prd')}>Read PRD</LinkButton></>);
      break;
    case 'pr_ready': {
      icon = 'merge'; tone = 'ship'; title = `PR #${item.pr} is ready to merge`;
      meta = [where, item.issue ? `#${item.issue} ${item.title}` : item.title];
      const n = typeof item.checks === 'number' ? item.checks : item.checks?.total;
      detail = `${item.reviewer ? `Approved by ${item.reviewer}. ` : 'Approved. '}${n ? `All ${n} checks pass.` : 'Checks pass.'}`;
      acts = <Button sm variant="primary" onClick={() => a.panel.open({ kind: 'pr', repo, n: item.pr })}>Review and merge</Button>;
      break;
    }
    case 'grind_paused':
      icon = 'pause'; tone = 'review'; title = `Grind paused on PR #${item.pr}`;
      meta = [where, item.issue ? `#${item.issue}` : undefined, item.round ? `round ${item.round}` : undefined]; detail = item.reason;
      acts = (<>
        <Button sm onClick={() => void a.skipCi(repo, item.pr)}>Skip CI and continue</Button>
        <Button sm onClick={() => void a.stopGrind(repo, item.pr)}>Stop grind</Button>
        <Button sm variant="primary" onClick={() => a.panel.open({ kind: 'pr', repo, n: item.pr })}>Open PR</Button>
      </>);
      break;
    case 'session_failed':
      icon = 'alert'; tone = 'bad'; title = `${cmdName(item.command)} failed`; meta = [where, at && `${at} ago`]; detail = item.error;
      acts = (<>
        <Button sm onClick={() => void a.terminal(item.session_id)}>Continue in terminal</Button>
        {sess(item.session_id)}
        <Button sm variant="primary" onClick={() => a.retry(item.session_id)}>Retry</Button>
      </>);
      break;
    case 'needs_cleanup':
      icon = 'trash'; title = `Worktree for #${item.issue} has unsaved work`; meta = [where, 'merged'];
      detail = `${item.uncommitted.length} uncommitted file${item.uncommitted.length === 1 ? '' : 's'}, ${item.unpushed.length} unpushed commit${item.unpushed.length === 1 ? '' : 's'}. Merged worktrees are removed automatically only when clean.`;
      acts = <Button sm variant="primary" onClick={() => void a.cleanup(repo, item.issue, item.uncommitted, item.unpushed)}>Review and clean up</Button>;
      break;
    case 'repo_unpublished':
      icon = 'github'; title = `${shortRepo(item.slug)} has no GitHub remote`; meta = [item.path];
      detail = 'Planning, issues and PRs need a GitHub repo. Publishing creates the repo and pushes this branch.';
      acts = <Button sm variant="primary" onClick={() => publish(item.slug)}>Publish to GitHub</Button>;
      break;
    case 'limited': {
      icon = 'clock'; tone = 'review'; title = `${cmdName(item.command)} paused by usage limit`;
      meta = [where, `${item.account} account`, item.auto_resume ? `resumes ${clockText(item.resets_at)}` : 'auto-resume off'];
      const others = (settings.data?.commands ?? []).filter((c) => c.label !== item.account);
      acts = (<>
        <Menu items={others.map((c) => ({ label: c.label, onSelect: () => a.resumeOn(item.session_id, c.label) }))} trigger={<Button sm disabled={!others.length}>Resume on another account</Button>} />
        {sess(item.session_id)}
      </>);
      break;
    }
    case 'queued':
      icon = 'clock'; title = `${cmdName(item.command)} is queued`; meta = [where, item.reason];
      acts = (<><Button sm onClick={() => a.startNow(item.session_id)}>Start now</Button><Button sm variant="ghost" onClick={() => void a.cancel(item.session_id)}>Cancel</Button></>);
      break;
  }
  return (
    <div className="item">
      <div className={`item-ico t-${tone}`}><Icon n={icon} /></div>
      <div style={{ minWidth: 0 }}>
        <div className="item-title">{title}</div>
        <div className="item-meta">
          {meta.filter(Boolean).map((m, j) => (<span key={j} style={{ display: 'contents' }}>{j ? <span className="sep">/</span> : null}<span>{m}</span></span>))}
        </div>
        {detail ? <p style={{ marginTop: 6 }}>{detail}</p> : null}
      </div>
      <div className="item-actions">{acts}</div>
      {body ? <div className="item-body">{body}</div> : null}
    </div>
  );
}
