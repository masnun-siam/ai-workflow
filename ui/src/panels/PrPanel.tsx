import { useState } from 'react';
import { useComment, useDelivery, useMerge, usePull, useSkipCi, useStopGrind } from '../api/hooks';
import type { PrCheck, PrCommitRow, PrConvItem, PrFileRow } from '../api/types';
import { Banner, Button, Chip, EmptyState, ExtButton, TabPanel, Tabs, toast, useConfirm } from '../components';
import { formatWhen, grindLabel } from '../lib/format';
import { PanelFrame } from './DetailPanel';
import { who } from './IssuePanel';
import { mergeWarnings } from './prWarnings';
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

export function PrPanel({ repo, n }: { repo: string; n: number }) {
  const q = usePull(repo, n);
  const del = useDelivery(repo);
  const merge = useMerge();
  const skip = useSkipCi();
  const stop = useStopGrind();
  const comment = useComment();
  const confirm = useConfirm();
  const [tab, setTab] = useState('overview');
  const [asking, setAsking] = useState(false);
  const [mergeErr, setMergeErr] = useState('');
  const [text, setText] = useState('');

  const d = q.data;
  if (q.isError)
    return (
      <PanelFrame title={`PR #${n}`} subtitle={repo}>
        <EmptyState icon="alert" title="Could not load this pull request" actions={<Button onClick={() => q.refetch()}>Retry</Button>}>{q.error.message}</EmptyState>
      </PanelFrame>
    );
  if (!d)
    return (
      <PanelFrame title={`PR #${n}`} subtitle={repo}>
        <p className="muted" role="status">Loading…</p>
      </PanelFrame>
    );

  const checks = (Array.isArray(d.checks) ? d.checks : []) as unknown as PrCheck[];
  const conv = (d.conversation ?? []) as unknown as PrConvItem[];
  const files = (d.files ?? []) as unknown as PrFileRow[];
  const commits = (d.commits ?? []) as unknown as PrCommitRow[];
  const warnings = mergeWarnings(checks, conv);
  const card = del.data?.lanes.flatMap((l) => l.cards).find((c) => c.pr?.n === n);
  const grind = card?.grind ?? null;
  const [stLabel, stTone] = STATE[d.state] ?? [d.state, 'muted' as const];
  const bad = checks.filter((c) => c.bucket === 'red').length;
  const wait = checks.filter((c) => c.bucket === 'pending').length;
  const reviews: Record<string, string> = {};
  for (const c of conv) if (c.kind === 'review' && c.verdict) reviews[c.author] = c.verdict;

  const doMerge = () => {
    setMergeErr('');
    merge.mutate(
      { repo, n },
      { onSuccess: () => { setAsking(false); toast(`Merged PR #${n}`); }, onError: (e) => setMergeErr(e.message) },
    );
  };
  const doStop = async () => {
    if (await confirm({ title: 'Stop the grind?', okLabel: 'Stop grind', danger: true, body: <p>Marks the review loop done. The PR stays open and nothing is merged.</p> }))
      stop.mutate({ repo, pr: n }, { onSuccess: () => toast('Grind stopped') });
  };

  return (
    <PanelFrame
      title={<>PR #{n} {d.title}</>}
      subtitle={`${repo} · ${d.head} into ${d.base}`}
      head={<div className="row wrap"><Chip tone={stTone}>{stLabel}</Chip><b className="p-add">+{d.additions}</b><b className="p-del">−{d.deletions}</b></div>}
      footer={
        asking ? (
          <div className="stack" style={{ width: '100%' }} role="alertdialog" aria-label="Confirm merge">
            <p><b>Merge PR #{n} into {d.base} with a merge commit?</b></p>
            {warnings.length ? <Banner tone="review" icon="alert"><p>Warning: {warnings.join(', ')}.</p></Banner> : null}
            {mergeErr ? <Banner tone="bad" icon="alert"><p>{mergeErr}</p></Banner> : null}
            <div className="row">
              <Button variant="primary" autoFocus disabled={merge.isPending} onClick={doMerge}>{warnings.length ? 'Merge anyway' : 'Merge'}</Button>
              <Button variant="ghost" onClick={() => setAsking(false)}>Cancel</Button>
            </div>
          </div>
        ) : (
          <>
            {d.state === 'open' ? <Button variant={warnings.length ? 'default' : 'primary'} onClick={() => setAsking(true)}>Merge…</Button> : null}
            {d.state === 'draft' ? <span className="muted">Draft PRs cannot be merged. Mark it ready on GitHub first.</span> : null}
            <span className="grow" />
            <ExtButton sm href={d.url}>Open on GitHub</ExtButton>
          </>
        )
      }
    >
      <Tabs
        value={tab}
        onValueChange={setTab}
        label="Pull request"
        tabs={[
          { value: 'overview', label: 'Overview' },
          { value: 'checks', label: 'Checks', count: checks.length || undefined },
          { value: 'conversation', label: 'Conversation', count: conv.length || undefined },
          { value: 'files', label: 'Files', count: d.file_count },
          { value: 'commits', label: 'Commits', count: d.commit_count },
        ]}
      >
        <TabPanel value="overview">
          <div className="stack">
            <p className="muted" style={{ fontSize: 13 }}>{who(d.author)} opened {formatWhen(d.created_at)}</p>
            {grind ? (
              <div className="box">
                <div className="row wrap">
                  <Chip tone={grind.state === 'paused' ? 'bad' : 'review'}>{grindLabel({ state: grind.state, round: grind.round })}</Chip>
                  {grind.reason ? <span className="muted">{grind.reason}</span> : null}
                  <span className="grow" />
                  {grind.state === 'paused' ? <Button sm disabled={skip.isPending} onClick={() => skip.mutate({ repo, pr: n }, { onSuccess: () => toast('Skipping CI and continuing') })}>Skip CI</Button> : null}
                  <Button sm variant="danger" disabled={stop.isPending} onClick={doStop}>Stop</Button>
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
            {d.body_html ? <Html html={d.body_html} /> : <p className="muted">No description.</p>}
          </div>
        </TabPanel>
        <TabPanel value="checks">
          {checks.length ? (
            <ul className="checks" style={{ listStyle: 'none', padding: 0 }}>
              {checks.map((c, i) => (
                <li key={i} className="check">
                  <Chip tone={c.bucket === 'red' ? 'bad' : c.bucket === 'pending' ? 'review' : 'ship'}>{c.bucket === 'red' ? 'Failed' : c.bucket === 'pending' ? 'Running' : 'Passed'}</Chip>
                  {c.link && /^https:/.test(c.link) ? <a href={c.link} target="_blank" rel="noopener noreferrer">{c.name}</a> : c.name}
                </li>
              ))}
            </ul>
          ) : <p className="muted">No checks reported.</p>}
        </TabPanel>
        <TabPanel value="conversation">
          <div className="stack">
            {conv.length ? conv.map((c, i) => (
              <article key={i} className="p-comment">
                <div className="who"><b>{c.author}</b>{c.kind === 'review' ? ` ${VERDICT[c.verdict ?? ''] ?? c.verdict}` : ''} · {formatWhen(c.at)}</div>
                {c.body_html ? <Html html={c.body_html} /> : null}
              </article>
            )) : <p className="muted">No comments or reviews yet.</p>}
            <label className="sr" htmlFor="pr-comment">Comment</label>
            <textarea id="pr-comment" className="f" rows={3} placeholder="Leave a comment" value={text} onChange={(e) => setText(e.target.value)} />
            <div><Button disabled={!text.trim() || comment.isPending} onClick={() => comment.mutate({ kind: 'pulls', repo, n, text: text.trim() }, { onSuccess: () => { setText(''); toast('Comment posted'); } })}>Comment</Button></div>
          </div>
        </TabPanel>
        <TabPanel value="files">
          <div className="stack" style={{ gap: 4 }}>
            <p className="muted">{d.file_count} file{d.file_count === 1 ? '' : 's'} changed</p>
            {tab === 'files' ? files.map((f) => <File key={f.name} f={f} />) : null}
            {d.file_count > files.length ? <p className="muted">{d.file_count - files.length} more on GitHub.</p> : null}
          </div>
        </TabPanel>
        <TabPanel value="commits">
          <div>
            {commits.map((c) => (
              <div key={c.sha} className="p-commit"><span className="mono muted">{c.sha.slice(0, 7)}</span><span>{c.subject}<span className="muted"> · {who(c.author)} · {formatWhen(c.at)}</span></span></div>
            ))}
            {d.commit_count > commits.length ? <p className="muted">{d.commit_count - commits.length} more on GitHub.</p> : null}
          </div>
        </TabPanel>
      </Tabs>
    </PanelFrame>
  );
}
