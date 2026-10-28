// FR-20, FR-21: one page per session. Header, state banners, transcript, composer, facts.
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useCancelAuto, useSession, useSettings, useStartNow, useTranscript, useVaultPrd } from '../api/hooks';
import type { Session } from '../api/types';
import { Banner, Button, Chip, EmptyState, Icon, Menu, SessionChip } from '../components';
import { QuestionForm } from '../questions/QuestionForm';
import { CreateRepoDialog } from '../repos/CreateRepoDialog';
import { issueOf } from '../activity/SessionTable';
import { clockText, duration, formatWhen, money, sessionLabel, sessionSlug, shortRepo, skillOf, tokensText, untilText } from '../lib/format';
import { routes } from '../lib/routes';
import { usePanel } from '../panels/PanelContext';
import { Composer } from '../session/Composer';
import { copyCommand, resumeCommand } from '../session/terminal';
import { Transcript } from '../session/Transcript';
import { useSessionActions } from '../session/useSessionActions';

// Stable ref callback: runs once when the question appears, not on every poll.
const reveal = (el: HTMLElement | null) => el?.scrollIntoView({ block: 'nearest' });

const PEER_TONE: Record<string, 'ship' | 'bad' | 'review'> = { approved: 'ship', 'cap reached': 'bad', failed: 'bad' };

export function PeerChip({ p }: { p: NonNullable<Session['peer_review']> }) {
  return (
    <Chip tone={PEER_TONE[p.state] ?? 'review'} title="Read from the review's rounds, not from what the session said">
      Peer review: {p.state} · {p.approved}/{p.total} approve{p.round ? ` · round ${p.round}` : ''}
    </Chip>
  );
}

function VaultPrd({ s }: { s: Session }) {
  const prd = useVaultPrd(s.vault_folder ?? '');
  const [dlg, setDlg] = useState(false);
  return (
    <Banner tone="plan" icon="file" action={<Button sm variant="primary" onClick={() => setDlg(true)}>Create repo</Button>}>
      <p><b>{prd.data?.exists ? `PRD in the notes vault: ${prd.data.title ?? prd.data.path}` : 'No PRD found in the notes vault yet.'}</b>{prd.data?.status ? ` Status: ${prd.data.status}.` : ''}</p>
      <p className="muted">Create a repo to start planning and building this feature on GitHub.</p>
      <CreateRepoDialog open={dlg} vaultFolder={s.vault_folder ?? ''} onClose={() => setDlg(false)} />
    </Banner>
  );
}

export function SessionPage() {
  const { id = '' } = useParams();
  const panel = usePanel();
  const q = useSession(id);
  const s = q.data;
  const live = !!s && (['starting', 'running'].includes(s.outcome) || (s.outcome === 'waiting' && !s.ended_at));
  const tr = useTranscript(id, live);
  const accounts = useSettings().data?.commands ?? [];
  const a = useSessionActions();
  const startNowM = useStartNow();
  const cancelAuto = useCancelAuto();

  if (q.error instanceof ApiError && q.error.status === 404) {
    return <div className="content-inner"><EmptyState icon="search" title="Session not found" actions={<Link className="btn" to={routes.activity}>Back to activity</Link>}>It may have been cleaned up.</EmptyState></div>;
  }
  if (!s) {
    return (
      <div className="content-inner">
        {q.isError ? <Banner tone="bad" icon="alert" action={<Button sm onClick={() => void q.refetch()}>Retry</Button>}>Could not load the session. {q.error.message}</Banner> : <div className="skel" style={{ height: 160 }} />}
      </div>
    );
  }
  const issue = issueOf(s);
  const slug = sessionSlug(s);
  const finished = ['done', 'failed', 'stopped'].includes(s.outcome);
  const others = accounts.filter((c) => c.cmd !== s.claude_cmd);
  const account = accounts.find((c) => c.cmd === s.claude_cmd)?.label ?? '';
  const term = () => void copyCommand(resumeCommand(s));
  const startNow = () => startNowM.mutate(s.id);

  return (
    <div className="content-inner">
      <div className="crumbs"><Link to={routes.activity} style={{ color: 'inherit' }}>Activity</Link><Icon n="right" s={13} /><span className="mono">{sessionLabel(s.command)}</span></div>
      <div className="page-head">
        <div className="grow">
          <div className="row wrap" style={{ gap: 10 }}>
            <h1 className="mono clamp2" title={sessionLabel(s.command)} style={{ fontSize: 17, fontWeight: 500, lineHeight: 1.4, overflowWrap: 'anywhere', maxWidth: 'none' }}>{sessionLabel(s.command)}</h1>
            <SessionChip s={s.outcome} />
            {s.peer_review ? <PeerChip p={s.peer_review} /> : null}
          </div>
          <p className="sub">
            {issue && slug ? <button type="button" className="linkish" onClick={() => panel.open({ kind: 'issue', repo: slug, n: issue })}>Issue #{issue}</button> : s.no_repo ? 'Notes vault' : shortRepo(slug || s.repo)}
          </p>
        </div>
        <div className="row wrap">
          {s.outcome === 'stopped' ? <Button shortcut="r" primary disabled={a.busy} onClick={() => a.resume(s.id)}>Resume</Button> : null}
          {finished ? <Button shortcut="r" disabled={a.busy} onClick={() => a.rerun(s.id)}><Icon n="refresh" />Rerun</Button> : null}
          {s.session_id ? <Button shortcut="t" onClick={term}><Icon n="terminal" />Continue in terminal</Button> : null}
          {!finished ? <Button shortcut="x" variant="danger" onClick={() => void a.stop(s.id)}><Icon n="stop" />Stop</Button> : null}
        </div>
      </div>

      {s.outcome === 'limited' ? (
        <Banner
          tone="review"
          icon="clock"
          action={
            <div className="row wrap">
              <Menu paletteLabel="Resume on" items={others.map((c) => ({ label: c.label, onSelect: () => a.resume(s.id, c.label) }))} trigger={<Button sm disabled={!others.length}>Resume on another account</Button>} />
              {s.auto_resume ? <Button sm variant="ghost" onClick={() => cancelAuto.mutate(s.id)}>Don't auto-resume</Button> : null}
            </div>
          }
        >
          <p><b>Paused: {account || 'the'} account hit its usage limit.</b> {s.limit_resets_at ? (s.auto_resume ? `Resumes on its own at ${clockText(s.limit_resets_at)} (${untilText(s.limit_resets_at)}).` : `Resets at ${clockText(s.limit_resets_at)} (${untilText(s.limit_resets_at)}). Auto-resume is off.`) : 'Auto-resume is off.'}</p>
        </Banner>
      ) : null}
      {s.outcome === 'failed' ? (
        <Banner tone="bad" icon="alert" action={<div className="row wrap">{s.session_id ? <Button sm shortcut="t" onClick={term}>Continue in terminal</Button> : null}<Button sm shortcut="r" variant="primary" disabled={a.busy} onClick={() => a.resume(s.id)}>Retry</Button></div>}>
          <p><b>Failed.</b> {s.error ?? 'No error was recorded.'}</p>
          <p className="muted">Retry starts it again. Continue in terminal picks up this exact conversation.</p>
        </Banner>
      ) : null}
      {s.outcome === 'queued' ? (
        <Banner tone="muted" icon="clock" action={<Button sm onClick={startNow}>Start now</Button>}><p>{s.note ?? 'Queued.'}</p></Banner>
      ) : null}
      {finished && s.no_repo && skillOf(s.command) === 'create-prd' && s.vault_folder ? <VaultPrd s={s} /> : null}

      <div className="sess-grid">
        <div className="stack">
          <Transcript events={tr.events} live={live} working={['running', 'starting'].includes(s.outcome)} />
          {s.outcome === 'waiting' ? (
            <section className="stack" style={{ gap: 8 }} ref={reveal}>
              <h2 style={{ color: 'var(--you)' }}>Claude is waiting on you</h2>
              <QuestionForm sessionId={s.id} />
            </section>
          ) : null}
          <Composer s={s} />
        </div>
        <aside className="box" aria-label="Facts">
          <dl className="facts">
            <dt>Repo</dt><dd>{s.no_repo ? 'Notes vault' : shortRepo(slug || s.repo)}</dd>
            {account ? <><dt>Account</dt><dd>{account}</dd></> : null}
            <dt>Started</dt><dd>{formatWhen(s.started_at)}</dd>
            <dt>Duration</dt><dd>{duration(s.started_at, s.ended_at)}</dd>
            <dt>Cost</dt><dd>{money(s.cost)}</dd>
            <dt>Tokens</dt><dd>{tokensText(s.tokens) || '—'}</dd>
            <dt>Model</dt><dd>{s.model || '—'}</dd>
            <dt>Effort</dt><dd>{s.effort || 'Default'}</dd>
            {issue ? <><dt>Issue</dt><dd>#{issue}</dd></> : null}
          </dl>
        </aside>
      </div>
    </div>
  );
}
