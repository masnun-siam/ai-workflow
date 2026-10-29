import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../api/client';
import { api } from '../api/endpoints';
import { keys, useMarkSeen, usePrd, useSavePrd } from '../api/hooks';
import type { ShareThread } from '../api/types';
import { useStarter } from '../board/actions';
import { Banner, Button, EmptyState, useConfirm } from '../components';
import { placeThreads, type Placements } from '../lib/anchor';
import { bodyText, highlight } from '../lib/anchorDom';
import type { Feature } from '../lib/features';
import { mdToHtml } from '../lib/md';
import { prdBody, renderDiagrams, toggleDiagram } from '../lib/prdRender';
import { PLAN_RUN } from '../lib/vocab';
import { SharePopover } from './SharePopover';
import { SendComments } from './SendComments';
import { ThreadRail } from './ThreadRail';
import { useOwnShare } from './useOwnShare';

export const CHANGED_MSG = 'This file changed on disk since you opened it, so nothing was saved. Reload it, then redo your edit.';
export const askArgs = (path: string, text: string) => `${path} --update ${text.trim()}`;

const NO_THREADS: ShareThread[] = [];
const newestComment = (threads: ShareThread[]) => threads.reduce((m, t) => t.comments.reduce((n, c) => (c.at > n ? c.at : n), m), '');

export function PrdTab({ f, repo }: { f: Feature; repo: string }) {
  const path = f.prd.path;
  const q = usePrd(repo, path);
  const qc = useQueryClient();
  const save = useSavePrd();
  const confirm = useConfirm();
  const starter = useStarter();
  const [mode, setMode] = useState<'read' | 'edit'>('read');
  const [draft, setDraft] = useState('');
  const [err, setErr] = useState('');
  const [note, setNote] = useState('');
  const [ask, setAsk] = useState('');
  const data = q.data;
  const prose = useRef<HTMLDivElement>(null);
  useEffect(() => { if (mode === 'read') void renderDiagrams(prose.current); }, [mode, data?.text]);
  const { share: shareQ } = useOwnShare(repo, path);
  const share = shareQ.data;
  const threads = share?.threads ?? NO_THREADS;
  const markSeen = useMarkSeen();
  const [placements, setPlacements] = useState<Placements | null>(null);
  const prev = useRef<Placements | null>(null);
  // "New" compares against last_seen_at as it was when the tab opened, so markers survive the seen post.
  const baseline = useRef<{ id: string; at: string | null } | null>(null);
  if (share && baseline.current?.id !== share.id) baseline.current = { id: share.id, at: share.last_seen_at };
  const newest = newestComment(threads);
  useEffect(() => { if (share?.id) markSeen.mutate(share.id); }, [share?.id, newest]); // eslint-disable-line react-hooks/exhaustive-deps
  // Highlights go on after the prose renders; the undo runs before the next pass, so anchors always see clean text.
  useEffect(() => {
    const el = prose.current;
    if (mode !== 'read' || !el) { setPlacements(null); return; }
    const p = placeThreads(bodyText(el), threads, prev.current ?? undefined);
    prev.current = p;
    setPlacements(p);
    const spans = threads.flatMap((t) => { const s = p.spans.get(t.id); return s ? [{ id: t.id, ...s }] : []; });
    return highlight(el, spans);
  }, [data?.text, mode, threads]);
  const branch = typeof data?.branch === 'string' ? data.branch : 'the current branch';
  const dirty = mode === 'edit' && !!data && draft !== data.text;
  // The page heading already names the feature, so the PRD's own title is dropped when reading.
  const body = prdBody(data?.text ?? '');
  const heads = body.split('\n').filter((l) => l.startsWith('## ')).map((l) => l.slice(3).trim());
  const words = body.split(/\s+/).filter(Boolean).length;
  const jump = (k: number) => prose.current?.querySelectorAll('h2')[k]?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const jumpToThread = (id: string) => prose.current?.querySelector(`mark.anchor-hl[data-thread="${id}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  const onProseClick = (e: React.MouseEvent) => {
    toggleDiagram(e);
    const id = (e.target as Element).closest<HTMLElement>('mark.anchor-hl')?.dataset.thread;
    const card = id ? document.getElementById(`thread-${id}`) : null;
    card?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    card?.focus({ preventScroll: true });
  };

  const discard = async () => {
    if (dirty && !(await confirm({ title: 'Discard your edits?', okLabel: 'Discard', danger: true, body: <p>Your unsaved changes to this PRD will be lost.</p> }))) return false;
    setDraft(data?.text ?? '');
    setErr('');
    return true;
  };
  const doSave = () => {
    if (!data) return;
    setErr('');
    save.mutate(
      { repo, path, text: draft, base_sha: data.sha },
      {
        onSuccess: (r) => {
          const rr = r as { committed?: boolean; commit?: string; branch?: string };
          setNote(rr.committed ? `Committed ${rr.commit} on ${rr.branch} (not pushed)` : 'No changes to save');
          setMode('read');
        },
        onError: (e) => setErr(e instanceof ApiError && e.status === 409 ? CHANGED_MSG : e.message),
      },
    );
  };
  const reload = async () => {
    const r = await qc.fetchQuery({ queryKey: keys.prd(repo, path), queryFn: () => api.prd(repo, path), staleTime: 0 });
    setDraft(r.text);
    setErr('');
  };

  if (q.isError) return <EmptyState icon="alert" title="Could not read the PRD" actions={<Button onClick={() => q.refetch()}>Retry</Button>}>{q.error.message}</EmptyState>;
  if (!data) return <p className="muted" role="status">Loading the PRD…</p>;

  return (
    <div className="sess-grid">
      <div className="stack">
        <div className="row">
          <div className="seg" role="group" aria-label="PRD mode">
            <button type="button" className={mode === 'read' ? 'on' : ''} aria-pressed={mode === 'read'} onClick={async () => { if (mode === 'edit' && !(await discard())) return; setMode('read'); }}>Read</button>
            <button type="button" className={mode === 'edit' ? 'on' : ''} aria-pressed={mode === 'edit'} onClick={() => { if (mode !== 'edit') { setDraft(data.text); setNote(''); setMode('edit'); } }}>Edit</button>
          </div>
          <span className="grow" />
          <SharePopover status={f.prd.status} repo={repo} path={path} />
          <span className="muted" style={{ fontSize: 12.5 }}>{f.prd.status} · {words.toLocaleString()} words</span>
        </div>
        {note ? <p role="status" className="muted">{note}</p> : null}
        {mode === 'read' ? (
          <div ref={prose} onClick={onProseClick} className="prose box" style={{ padding: '18px 22px' }} dangerouslySetInnerHTML={{ __html: mdToHtml(body) }} />
        ) : (
          <div className="stack">
            <label className="sr" htmlFor="prd-text">PRD markdown</label>
            <textarea id="prd-text" className="f prd-edit" rows={16} spellCheck={false} value={draft} onChange={(e) => setDraft(e.target.value)} />
            <Banner tone="review" icon="alert"><p>Saving commits only this file to <b>{branch}</b>, the branch the checkout is on. It is not pushed.</p></Banner>
            {err ? (
              <Banner tone="bad" icon="alert" action={err === CHANGED_MSG ? <Button sm onClick={reload}>Reload</Button> : undefined}><p>{err}</p></Banner>
            ) : null}
            <div className="row">
              <Button variant="primary" disabled={!dirty || save.isPending} onClick={doSave}>{save.isPending ? 'Saving…' : 'Save and commit'}</Button>
              <Button variant="ghost" onClick={async () => { if (await discard()) setMode('read'); }}>Discard</Button>
            </div>
          </div>
        )}
      </div>
      <div className="toc">
        {mode === 'read' && heads.length ? (
          <nav aria-label="PRD sections">
            <ol>{heads.map((h, k) => <li key={k}><button type="button" onClick={() => jump(k)}>{h}</button></li>)}</ol>
          </nav>
        ) : null}
        {share ? <ThreadRail share={share} placements={placements} baseline={baseline.current?.at ?? null} onJump={jumpToThread} extra={(outdatedIds) => <SendComments share={share} outdatedIds={outdatedIds} refetch={() => void shareQ.refetch()} />} /> : null}
        <div className="box">
          <h3>Ask Claude to change it</h3>
          <p className="muted" style={{ fontSize: 13 }}>Runs <code>/create-prd --update</code>, which records the decision in the PRD.</p>
          <label className="sr" htmlFor="prd-ask">What should change?</label>
          <textarea id="prd-ask" className="f" rows={4} placeholder="Example: Guests should be able to see reports but not export them." value={ask} onChange={(e) => setAsk(e.target.value)} />
          <Button disabled={!ask.trim() || starter.pending} onClick={async () => { const id = await starter.startSession({ repo, command: 'create-prd', args: askArgs(path, ask), ...PLAN_RUN }); if (id) setAsk(''); }}>Start update</Button>
        </div>
      </div>
    </div>
  );
}
