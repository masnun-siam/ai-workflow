import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { type Anchor, type Placements, placeThreads } from '../lib/anchor';
import { bodyText, highlight } from '../lib/anchorDom';
import { formatWhen } from '../lib/format';
import { mdToHtml } from '../lib/md';
import { prdBody, renderDiagrams, toggleDiagram } from '../lib/prdRender';
import { getApprovals, getPrd, getThreads, postComment, postError, postThread, ShareError } from './api';
import { Approve } from './Approve';
import { CommentButton, ComposeForm, OutdatedList, ThreadCard, useIdentity } from './Comments';
import { useBodySelection } from './selection';
import { placeSlots, type Slot } from './slots';
import type { PublicApproval, PublicPrd, PublicThread } from './types';

const POLL_MS = 30_000;
const FULL_AT = 500;
const NEW = 'new';

export function SharePage() {
  const [prd, setPrd] = useState<PublicPrd | null>(null);
  const [threads, setThreads] = useState<PublicThread[]>([]);
  const [approvals, setApprovals] = useState<PublicApproval[] | null>(null);
  const [gone, setGone] = useState(false);
  const [offline, setOffline] = useState(false);
  const [bodyTxt, setBodyTxt] = useState<string>();
  const [slots, setSlots] = useState<Slot[]>([]);
  const [newAnchor, setNewAnchor] = useState<Anchor | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [fullSeen, setFullSeen] = useState(false);
  const [focusId, setFocusId] = useState<string | null>(null);
  const prose = useRef<HTMLDivElement>(null);
  const draftBox = useRef<HTMLTextAreaElement>(null);
  const placed = useRef<Placements>();
  const who = useIdentity();
  const [sel, clearSel] = useBodySelection(prose);

  useEffect(() => {
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      let again = true;
      try {
        const [next, list, appr] = await Promise.all([getPrd(ctl.signal), getThreads(ctl.signal), getApprovals(ctl.signal)]);
        if (ctl.signal.aborted) return;
        // Keep the old objects when nothing changed so React leaves the rendered body alone.
        setPrd((cur) => (cur && cur.text === next.text && cur.title === next.title && cur.status === next.status && cur.updated_at === next.updated_at ? cur : next));
        const fresh = Array.isArray(list) ? list : [];
        setThreads((cur) => (JSON.stringify(cur) === JSON.stringify(fresh) ? cur : fresh));
        const freshAppr = Array.isArray(appr) ? appr : [];
        setApprovals((cur) => (JSON.stringify(cur) === JSON.stringify(freshAppr) ? cur : freshAppr));
        setOffline(false);
      } catch (e) {
        if (ctl.signal.aborted) return;
        if (e instanceof ShareError && e.status === 404) { setGone(true); again = false; } else setOffline(true);
      }
      if (again) timer = setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => { ctl.abort(); clearTimeout(timer); };
  }, []);

  const text = prd?.text;
  useEffect(() => { if (text !== undefined) void renderDiagrams(prose.current); }, [text]);
  const html = text === undefined ? '' : mdToHtml(prdBody(text));
  // Anchors live in the rendered text, so it is read back once the HTML is in the DOM.
  useEffect(() => { if (prose.current) setBodyTxt(bodyText(prose.current)); }, [html]);

  const placements = useMemo(() => {
    if (bodyTxt === undefined) return undefined;
    const next = placeThreads(bodyTxt, threads.map((t) => ({ id: t.id, anchor: t.anchor, created_at: t.comments[0]?.at ?? '' })), placed.current);
    placed.current = next;
    return next;
  }, [bodyTxt, threads]);

  useEffect(() => {
    const root = prose.current;
    if (!root || !placements) return;
    const spans = [...placements.spans].flatMap(([id, s]) => (s ? [{ id, ...s }] : []));
    const undo = highlight(root, spans);
    const made = placeSlots(root, spans);
    setSlots(made.slots);
    return () => { made.remove(); undo(); setSlots([]); };
  }, [html, placements]);

  useEffect(() => {
    if (!focusId) return;
    const el = Array.from(document.querySelectorAll<HTMLElement>('[data-thread-card]')).find((e) => e.dataset.threadCard === focusId);
    if (el) { el.focus(); setFocusId(null); }
  }, [focusId, slots, threads]);

  const full = fullSeen || threads.reduce((n, t) => n + t.comments.filter((c) => !c.by_owner).length, 0) >= FULL_AT;
  const setDraft = (key: string, v: string) => setDrafts((d) => ({ ...d, [key]: v }));

  const post = async (key: string, run: () => Promise<void>) => {
    setBusy(true);
    setErrors((e) => ({ ...e, [key]: '' }));
    try { await run(); } catch (e) {
      if (e instanceof ShareError && e.status === 404) setGone(true);
      else {
        if (e instanceof ShareError && e.status === 409) setFullSeen(true);
        setErrors((er) => ({ ...er, [key]: postError(e) }));
      }
    } finally { setBusy(false); }
  };

  const startThread = () => {
    if (!sel || sel.tooLong) return;
    if (newAnchor && drafts[NEW]?.trim()) { draftBox.current?.focus(); return; } // keep the draft being written
    setNewAnchor(sel.anchor);
    setDrafts((d) => ({ ...d, [NEW]: '' }));
    setTimeout(() => draftBox.current?.focus());
  };

  const sendThread = () => newAnchor && post(NEW, async () => {
    const t = await postThread({ name: who.name, body: drafts[NEW].trim(), anchor: newAnchor });
    who.remember(who.name);
    setThreads((cur) => [...cur.filter((x) => x.id !== t.id), t]);
    setNewAnchor(null); setDraft(NEW, ''); clearSel(); window.getSelection()?.removeAllRanges();
    setFocusId(t.id);
  });

  const sendReply = (t: PublicThread) => post(t.id, async () => {
    const c = await postComment(t.id, { name: who.name, body: (drafts[t.id] ?? '').trim() });
    who.remember(who.name);
    setThreads((cur) => cur.map((x) => (x.id === t.id ? { ...x, resolved: x.resolved && c.by_owner, comments: [...x.comments.filter((y) => y.id !== c.id), c] } : x)));
    setDraft(t.id, '');
  });

  const card = (t: PublicThread): ReactNode => (
    <ThreadCard key={t.id} thread={t} reply={
      <ComposeForm label="Reply" value={drafts[t.id] ?? ''} onChange={(v) => setDraft(t.id, v)} onSubmit={() => sendReply(t)} busy={busy} error={errors[t.id]} who={who} submit="Reply" />
    } />
  );

  const reloadApprovals = () => getApprovals().then(setApprovals).catch((e) => { if (e instanceof ShareError && e.status === 404) setGone(true); });
  const when = prd?.updated_at ? formatWhen(prd.updated_at) : '';

  if (gone) {
    const unsent = Object.values(drafts).filter((d) => d.trim());
    return (
      <main style={{ padding: 24 }}>
        <p>This link is no longer active</p>
        {unsent.map((d, i) => <textarea key={i} className="f" readOnly rows={4} aria-label="Your unsent comment" value={d} />)}
      </main>
    );
  }
  const outdated = threads.filter((t) => placements?.spans.get(t.id) === null);
  return (
    <main className="share-main" style={{ maxWidth: 860, margin: '0 auto', padding: '24px 16px' }}>
      {offline && <p role="status">Can't reach the PRD right now, retrying</p>}
      {!prd ? (!offline && <p>Loading the PRD…</p>) : (
        <>
          <h1>{prd.title}</h1>
          <p>{prd.status && <span>{prd.status}</span>}{prd.status && when !== '' && ' · '}{when !== '' && when !== '—' && `Last updated ${when}`}</p>
          {approvals && <Approve approvals={approvals} updatedAt={prd.updated_at} who={who} onList={(f) => setApprovals((cur) => f(cur ?? []))} reload={reloadApprovals} onGone={() => setGone(true)} />}
          <div ref={prose} onClick={toggleDiagram} className="prose box share-prose" style={{ padding: '18px 22px' }} dangerouslySetInnerHTML={{ __html: html }} />
          <CommentButton sel={sel} full={full} onClick={startThread} />
          {slots.map((s, i) => createPortal(s.ids.map((id) => threads.find((t) => t.id === id)).map((t) => t && card(t)), s.el, `${i}`))}
          {full && <p role="status">Share is full</p>}
          {newAnchor && (
            <ComposeForm ref={draftBox} className="comment-form box" label="Comment" quote={newAnchor.exact} value={drafts[NEW] ?? ''} onChange={(v) => setDraft(NEW, v)} onSubmit={sendThread} busy={busy} error={errors[NEW]} who={who} submit="Post" />
          )}
          {!threads.length && <p className="muted">No comments yet. Select text to comment</p>}
          <OutdatedList threads={outdated} card={card} />
        </>
      )}
    </main>
  );
}
