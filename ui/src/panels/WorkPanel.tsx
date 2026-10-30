// One panel per piece of work: the issue (Issue tab) and, once it has a PR, the PR's tabs beside it.
// Opened on an issue it starts on the Issue tab; opened on a PR (Merge, Open PR) on the PR's Overview.
// A PR with no issue on the board gets only the PR tabs.
import { useEffect, useRef, useState } from 'react';
import { useComment, useDelivery, useGrindIssue, useIssue, useMerge, usePull, useSetPrState, useSkipCi, useStopGrind } from '../api/hooks';
import type { PrCheck, PrCommitRow, PrConvItem, PrFileRow } from '../api/types';
import { actionKind, IssueAction } from '../board/IssueAction';
import { ResolveConflicts } from '../board/ResolveConflicts';
import { Banner, Button, Chip, EmptyState, ExtButton, IssueChip, LinkButton, Switch, TabPanel, Tabs, toast, useConfirm } from '../components';
import { useOwnedIssues } from '../dispatch/useOwner';
import { routes } from '../lib/routes';
import { STAGE, nowLine } from '../dispatch/vocab';
import { formatWhen, grindLabel } from '../lib/format';
import { issueStatus } from '../lib/vocab';
import { PanelFrame } from './DetailPanel';
import { FocusComment, IssueTab, issueStateText, who } from './IssuePanel';
import { mergeWarnings } from './prWarnings';
import { useFollowups } from './useFollowups';
import './panels.css';

const STATE: Record<string, [string, 'build' | 'ship' | 'muted' | 'bad']> = { open: ['PR open', 'build'], draft: ['Draft', 'muted'], merged: ['Merged', 'ship'], closed: ['PR closed', 'bad'] };
const VERDICT: Record<string, string> = { APPROVED: 'approved', CHANGES_REQUESTED: 'requested changes', COMMENTED: 'reviewed', DISMISSED: 'dismissed a review' };

function Html({ html }: { html: string }) {
  return <div className="p-html" dangerouslySetInnerHTML={{ __html: html }} />;
}

function File({ f }: { f: PrFileRow }) {
  const [open, setOpen] = useState(false);
  return (
    <details className="p-file" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        <span className="name">{f.from ? `${f.from} → ${f.name}` : f.name}</span>
        {f.status && f.status !== 'modified' ? <Chip>{f.status}</Chip> : null}
        <b className="p-add">+{f.additions}</b><b className="p-del">−{f.deletions}</b>
      </summary>
      {open ? (
        f.patch ? (
          <pre className="p-diff" tabIndex={0}>{f.patch.split('\n').map((l, i) => <span key={i} className={l[0] === '+' ? 'ln-add' : l[0] === '-' ? 'ln-del' : l[0] === '@' ? 'ln-hunk' : ''}>{l || ' '}</span>)}</pre>
        ) : (
          <p className="muted">{f.patch_cut ? 'This diff is too large to show here.' : 'No text diff for this file (binary or empty).'} Use Open on GitHub to see it.</p>
        )
      ) : null}
    </details>
  );
}

export function WorkPanel({ kind, repo, n }: { kind: 'issue' | 'pr'; repo: string; n: number }) {
  const del = useDelivery(repo);
  const cards = del.data?.lanes.flatMap((l) => l.cards) ?? [];
  const card = kind === 'issue' ? cards.find((c) => c.n === n) : cards.find((c) => c.pr?.n === n);
  const issueN = kind === 'issue' ? n : card?.n;
  const prN = kind === 'pr' ? n : card?.pr?.n;
  const iq = useIssue(repo, issueN ?? 0);
  const q = usePull(repo, prN ?? 0);
  const merge = useMerge();
  const setPrState = useSetPrState();
  const skip = useSkipCi();
  const stop = useStopGrind();
  const setGrind = useGrindIssue();
  const owner = useOwnedIssues(repo).get(issueN ?? -1);
  const comment = useComment();
  const followups = useFollowups(repo);
  const confirm = useConfirm();
  const [tab, setTab] = useState(kind === 'pr' ? 'overview' : 'issue');
  const [asking, setAsking] = useState(false);
  const [mergeErr, setMergeErr] = useState('');
  const mergeBtn = useRef<HTMLButtonElement>(null);
  const wasAsking = useRef(false);
  useEffect(() => {
    if (wasAsking.current && !asking) mergeBtn.current?.focus();
    wasAsking.current = asking;
  }, [asking]);
  const [closing, setClosing] = useState(false);
  const [stateErr, setStateErr] = useState('');
  const closeBtn = useRef<HTMLButtonElement>(null);
  const wasClosing = useRef(false);
  useEffect(() => {
    if (wasClosing.current && !closing) closeBtn.current?.focus();
    wasClosing.current = closing;
  }, [closing]);
  const [text, setText] = useState('');

  const d = prN ? q.data : undefined;
  const issue = issueN ? iq.data : undefined;
  const checks = (Array.isArray(d?.checks) ? d.checks : []) as unknown as PrCheck[];
  const conv = (d?.conversation ?? []) as unknown as PrConvItem[];
  const files = (d?.files ?? []) as unknown as PrFileRow[];
  const commits = (d?.commits ?? []) as unknown as PrCommitRow[];
  const warnings = mergeWarnings(checks, conv);
  const conflict = !!(d?.conflict || card?.pr?.conflict);
  const grind = card?.grind ?? null;
  const [stLabel, stTone] = d ? (STATE[d.state] ?? [d.state, 'muted' as const]) : ['', 'muted' as const];
  const bad = checks.filter((c) => c.bucket === 'red').length;
  const wait = checks.filter((c) => c.bucket === 'pending').length;
  const reviews: Record<string, string> = {};
  for (const c of conv) if (c.kind === 'review' && c.verdict) reviews[c.author] = c.verdict;
  // Merge and Open PR would only reopen this panel
  const act = card && !['merge', 'openPr'].includes(actionKind(card)) ? <IssueAction card={card} repo={repo} /> : null;

  const doMerge = () => {
    if (!prN) return;
    setMergeErr('');
    merge.mutate(
      { repo, n: prN },
      { onSuccess: () => { setAsking(false); toast(`Merged PR #${prN}`); if (issueN) void followups.offer(issueN, `PR #${prN} is merged`); }, onError: (e) => setMergeErr(e.message) },
    );
  };
  const doSetState = (state: 'open' | 'closed') => {
    if (!prN) return;
    setStateErr('');
    setPrState.mutate(
      { repo, n: prN, state },
      { onSuccess: () => { setClosing(false); toast(state === 'closed' ? `Closed PR #${prN}` : `Reopened PR #${prN}`); }, onError: (e) => { setStateErr(e.message); void q.refetch(); } },
    );
  };
  const doStop = async () => {
    if (prN && (await confirm({ title: 'Stop the grind?', okLabel: 'Stop grind', danger: true, body: <p>Marks the review loop done. The PR stays open and nothing is merged.</p> })))
      stop.mutate({ repo, pr: prN }, { onSuccess: () => toast('Grind stopped') });
  };
  const toggleGrind = async (on: boolean) => {
    if (!card) return;
    if (!on && grind && !(await confirm({ title: `Turn grinding off for #${card.n}?`, okLabel: 'Stop grind', danger: true, body: <p>The running grind stops. The PR stays open; Merge then needs green CI and an approval (none needed on your own repos).</p> })))
      return;
    const starts = on && !grind && card.pr && !card.pr.draft;
    setGrind.mutate({ repo, issue: card.n, on }, { onSuccess: () => toast(on ? (starts ? 'Grinding on, grind started' : 'Grinding on') : 'Grinding off') });
  };

  const prPending = (body: () => JSX.Element) =>
    q.isError ? <EmptyState icon="alert" title="Could not load this pull request" actions={<Button onClick={() => q.refetch()}>Retry</Button>}>{q.error.message}</EmptyState> : d ? body() : <p className="muted" role="status">Loading…</p>;

  const title = issue ? <>#{issueN} {issue.title}</> : d ? <>PR #{prN} {d.title}</> : kind === 'issue' ? `Issue #${n}` : `PR #${n}`;
  const subtitle = d ? `${repo} · ${d.head} into ${d.base}` : repo;
  const head = (
    <>
      <div className="row wrap">
        {issue ? <Chip tone={issue.state === 'open' ? 'build' : 'muted'}>{issueStateText(issue)}</Chip> : null}
        {card ? <IssueChip s={issueStatus(card)} /> : null}
        {d ? <><Chip tone={stTone}>{stLabel}</Chip><b className="p-add">+{d.additions}</b><b className="p-del">−{d.deletions}</b></> : null}
        {act}
      </div>
      {owner ? (
        <div className="row wrap">
          <Chip tone={STAGE[owner.l.stage].tone}>{STAGE[owner.l.stage].label}</Chip>
          <span className="muted grow" style={{ fontSize: 13 }}>A dispatch runs this issue: {nowLine(owner.l, owner.d.lanes).text.toLowerCase()}. It grinds and merges by its own settings.</span>
          <LinkButton sm to={`${routes.dispatch(owner.d.id)}?lane=${encodeURIComponent(owner.l.key)}`}>Open dispatch</LinkButton>
        </div>
      ) : card && card.column !== 'merged' ? (
        <div className="row wrap">
          <label className="row" style={{ gap: 8, fontWeight: 600 }}>
            <Switch checked={!!card.grind_on} label={`Grinding for #${card.n}`} disabled={setGrind.isPending} onChange={(on) => void toggleGrind(on)} />
            Grinding
          </label>
          <span className="muted" style={{ fontSize: 13 }}>{card.grind_on ? 'Merge shows once the grind is done, CI is green and the PR is approved.' : 'Merge shows once CI is green and the PR is approved.'}</span>
          <span className="grow" />
          {grind?.thread ? <ExtButton sm href={grind.thread}>Open Slack thread</ExtButton> : null}
        </div>
      ) : null}
    </>
  );
  const footer = d ? (
    closing ? (
      <div className="stack" style={{ width: '100%' }} role="alertdialog" aria-label="Confirm close" onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setClosing(false); } }}>
        <p><b>Close PR #{prN} without merging? The branch is kept.</b></p>
        {stateErr ? <Banner tone="bad" icon="alert"><p>{stateErr}</p></Banner> : null}
        <div className="row">
          <Button variant="primary" autoFocus disabled={setPrState.isPending} onClick={() => doSetState('closed')}>Close PR</Button>
          <Button variant="ghost" onClick={() => setClosing(false)}>Cancel</Button>
        </div>
      </div>
    ) : asking ? (
      <div className="stack" style={{ width: '100%' }} role="alertdialog" aria-label="Confirm merge" onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setAsking(false); } }}>
        <p><b>Merge PR #{prN} into {d.base} with a merge commit?</b></p>
        {warnings.length ? <Banner tone="review" icon="alert"><p>Warning: {warnings.join(', ')}.</p></Banner> : null}
        {mergeErr ? <Banner tone="bad" icon="alert"><p>{mergeErr}</p></Banner> : null}
        <div className="row">
          <Button variant="primary" autoFocus disabled={merge.isPending} onClick={doMerge}>{warnings.length ? 'Merge anyway' : 'Merge'}</Button>
          <Button variant="ghost" onClick={() => setAsking(false)}>Cancel</Button>
        </div>
      </div>
    ) : (
      <>
        {d.state === 'open' ? <Button ref={mergeBtn} shortcut="m" variant={warnings.length || conflict ? 'default' : 'primary'} disabled={conflict} onClick={() => setAsking(true)}>Merge…</Button> : null}
        {d.state === 'open' && conflict ? <><span className="muted">Conflicts with {d.base}.</span><ResolveConflicts repo={repo} url={d.url} n={prN!} primary /></> : null}
        {d.state === 'draft' ? <span className="muted">Draft PRs cannot be merged. Mark it ready on GitHub first.</span> : null}
        {d.state === 'open' || d.state === 'draft' ? <Button ref={closeBtn} disabled={setPrState.isPending} onClick={() => { setStateErr(''); setClosing(true); }}>Close PR…</Button> : null}
        {d.state === 'closed' ? <Button disabled={setPrState.isPending} onClick={() => doSetState('open')}>Reopen PR</Button> : null}
        <span className="grow" />
        <ExtButton sm href={d.url}>PR on GitHub</ExtButton>
        {stateErr ? <div style={{ flexBasis: '100%' }}><Banner tone="bad" icon="alert"><p>{stateErr}</p></Banner></div> : null}
      </>
    )
  ) : undefined;

  if (!prN && issueN)
    return <PanelFrame title={title} subtitle={subtitle} head={head}><IssueTab repo={repo} n={issueN} card={card} /></PanelFrame>;

  return (
    <PanelFrame title={title} subtitle={subtitle} head={head} footer={footer}>
      <Tabs
        value={tab}
        onValueChange={setTab}
        label={issueN ? 'Issue and pull request' : 'Pull request'}
        tabs={[
          ...(issueN ? [{ value: 'issue', label: 'Issue' }] : []),
          { value: 'overview', label: 'PR overview' },
          { value: 'checks', label: 'Checks', count: checks.length || undefined },
          { value: 'conversation', label: 'Conversation', count: conv.length || undefined },
          { value: 'files', label: 'Files', count: d?.file_count },
          { value: 'commits', label: 'Commits', count: d?.commit_count },
        ]}
      >
        {issueN ? <TabPanel value="issue"><IssueTab repo={repo} n={issueN} card={card} /></TabPanel> : null}
        <TabPanel value="overview">
          {prPending(() => (
            <div className="stack">
              <p className="muted" style={{ fontSize: 13 }}>{who(d!.author)} opened {formatWhen(d!.created_at)}</p>
              {grind ? (
                <div className="box">
                  <div className="row wrap">
                    <Chip tone={grind.state === 'paused' ? 'bad' : 'review'}>{grindLabel({ state: grind.state, round: grind.round })}</Chip>
                    {grind.reason ? <span className="muted">{grind.reason}</span> : null}
                    <span className="grow" />
                    {grind.state === 'paused' ? <Button sm shortcut="s" disabled={skip.isPending} onClick={() => skip.mutate({ repo, pr: prN! }, { onSuccess: () => toast('Skipping CI and continuing') })}>Skip CI</Button> : null}
                    <Button sm variant="danger" shortcut="x" disabled={stop.isPending} onClick={doStop}>Stop</Button>
                  </div>
                </div>
              ) : null}
              {Object.keys(reviews).length ? (
                <div className="stack" style={{ gap: 4 }}>
                  <h3>Reviews</h3>
                  {Object.entries(reviews).map(([a, v]) => <div key={a}>{a} {VERDICT[v] ?? v.toLowerCase()}</div>)}
                </div>
              ) : null}
              {checks.length ? <p><Chip tone={bad ? 'bad' : wait ? 'review' : 'ship'}>{bad ? `${bad} of ${checks.length} checks failing` : wait ? `${wait} of ${checks.length} checks running` : `All ${checks.length} checks passing`}</Chip></p> : null}
              {d!.body_html ? <Html html={d!.body_html} /> : <p className="muted">No description.</p>}
            </div>
          ))}
        </TabPanel>
        <TabPanel value="checks">
          {prPending(() => checks.length ? (
            <ul className="checks" style={{ listStyle: 'none', padding: 0 }}>
              {checks.map((c, i) => (
                <li key={i} className="check">
                  <Chip tone={c.bucket === 'red' ? 'bad' : c.bucket === 'pending' ? 'review' : 'ship'}>{c.bucket === 'red' ? 'Failed' : c.bucket === 'pending' ? 'Running' : 'Passed'}</Chip>
                  {c.link && /^https:/.test(c.link) ? <a href={c.link} target="_blank" rel="noopener noreferrer">{c.name}</a> : c.name}
                </li>
              ))}
            </ul>
          ) : <p className="muted">No checks reported.</p>)}
        </TabPanel>
        <TabPanel value="conversation">
          {prPending(() => (
            <div className="stack">
              <FocusComment id="pr-comment" />
              {conv.length ? conv.map((c, i) => (
                <article key={i} className="p-comment">
                  <div className="who"><b>{c.author}</b>{c.kind === 'review' ? ` ${VERDICT[c.verdict ?? ''] ?? c.verdict}` : ''} · {formatWhen(c.at)}</div>
                  {c.body_html ? <Html html={c.body_html} /> : null}
                </article>
              )) : <p className="muted">No comments or reviews yet.</p>}
              <label className="sr" htmlFor="pr-comment">Comment on the PR</label>
              <textarea id="pr-comment" className="f" rows={3} placeholder="Leave a comment" value={text} onChange={(e) => setText(e.target.value)} />
              <div><Button disabled={!text.trim() || comment.isPending} onClick={() => comment.mutate({ kind: 'pulls', repo, n: prN!, text: text.trim() }, { onSuccess: () => { setText(''); toast('Comment posted'); } })}>Comment</Button></div>
            </div>
          ))}
        </TabPanel>
        <TabPanel value="files">
          {prPending(() => (
            <div className="stack" style={{ gap: 4 }}>
              <p className="muted">{d!.file_count} file{d!.file_count === 1 ? '' : 's'} changed</p>
              {tab === 'files' ? files.map((f) => <File key={f.name} f={f} />) : null}
              {d!.file_count > files.length ? <p className="muted">{d!.file_count - files.length} more on GitHub.</p> : null}
            </div>
          ))}
        </TabPanel>
        <TabPanel value="commits">
          {prPending(() => (
            <div>
              {commits.map((c) => (
                <div key={c.sha} className="p-commit"><span className="mono muted">{c.sha.slice(0, 7)}</span><span>{c.subject}<span className="muted"> · {who(c.author)} · {formatWhen(c.at)}</span></span></div>
              ))}
              {d!.commit_count > commits.length ? <p className="muted">{d!.commit_count - commits.length} more on GitHub.</p> : null}
            </div>
          ))}
        </TabPanel>
      </Tabs>
    </PanelFrame>
  );
}
