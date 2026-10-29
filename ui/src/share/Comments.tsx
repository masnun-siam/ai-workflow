import { forwardRef, type ReactNode, useId, useState } from 'react';
import { countPoints, MAX_QUOTE } from '../lib/anchor';
import { getName, setName } from './storage';
import type { PublicThread } from './types';
import type { Sel } from './selection';

export const NAME_MAX = 60;
export const BODY_MAX = 2000;
const fits = (s: string, max: number) => { const n = countPoints(s.trim()); return n >= 1 && n <= max; };

/** The reviewer's name: asked once, then "Posting as <name>, change". */
export function useIdentity() {
  const [stored, setStored] = useState(getName);
  const [input, setInput] = useState('');
  const [changing, setChanging] = useState(false);
  const asking = !stored || changing;
  return {
    stored, input, setInput, asking,
    name: (asking ? input : stored).trim(),
    change: () => { setInput(stored); setChanging(true); },
    remember: (name: string) => { if (asking) { setName(name); setStored(name); setChanging(false); } },
  };
}
export type Identity = ReturnType<typeof useIdentity>;

export function NameField({ who }: { who: Identity }) {
  const id = useId();
  if (!who.asking) return <p className="muted plain">Posting as {who.stored}, <button type="button" className="btn ghost sm" onClick={who.change}>change</button></p>;
  return (
    <>
      <label className="sr" htmlFor={id}>Your name</label>
      <input id={id} className="f" placeholder="Your name" value={who.input} onChange={(e) => who.setInput(e.target.value)} />
    </>
  );
}

export function CommentButton({ sel, full, onClick }: { sel: Sel | null; full: boolean; onClick: () => void }) {
  if (!sel || full) return null;
  return (
    <button
      type="button" data-comment-ui className="btn primary comment-btn" aria-disabled={sel.tooLong || undefined}
      style={{ '--top': `${sel.top + 6}px`, '--left': `${sel.left}px` } as React.CSSProperties}
      onMouseDown={(e) => e.preventDefault()} onClick={() => { if (!sel.tooLong) onClick(); }}
    >
      {sel.tooLong ? `Select less text (max ${MAX_QUOTE.toLocaleString('en-US')} characters)` : 'Comment'}
    </button>
  );
}

interface FormProps { label: string; quote?: string; value: string; onChange: (v: string) => void; onSubmit: () => void; busy: boolean; error?: string; who: Identity; submit: string; className?: string }

export const ComposeForm = forwardRef<HTMLTextAreaElement, FormProps>(function ComposeForm(p, ref) {
  const id = useId();
  const valid = fits(p.value, BODY_MAX) && fits(p.who.name, NAME_MAX);
  return (
    <form data-comment-ui className={`compose ${p.className ?? ''}`} onSubmit={(e) => { e.preventDefault(); if (valid && !p.busy) p.onSubmit(); }}>
      {p.quote !== undefined && <blockquote className="plain quote">{p.quote}</blockquote>}
      <NameField who={p.who} />
      <label className="sr" htmlFor={id}>{p.label}</label>
      <textarea id={id} ref={ref} className="f" rows={3} placeholder={p.label} value={p.value} onChange={(e) => p.onChange(e.target.value)} />
      {p.error && <p role="alert" className="err">{p.error}</p>}
      <button type="submit" className="btn primary sm" disabled={!valid || p.busy}>{p.submit}</button>
    </form>
  );
});

const firstWords = (s: string) => { const w = s.trim().split(/\s+/); return w.slice(0, 8).join(' ') + (w.length > 8 ? '…' : ''); };

/** One thread: its comments and a reply form (`reply`). Resolved threads start collapsed. */
export function ThreadCard({ thread, reply }: { thread: PublicThread; reply: ReactNode }) {
  const [expanded, setExpanded] = useState(false);
  const first = thread.comments[0];
  return (
    <section className="thread" tabIndex={-1} data-thread-card={thread.id} aria-label={`Thread by ${first?.author ?? 'a reviewer'}`}>
      {thread.resolved && !expanded ? (
        <button type="button" className="thread-sum plain" aria-expanded="false" onClick={() => setExpanded(true)}>
          <b>{first?.author}</b> {first && firstWords(first.body)} <span className="muted">(resolved)</span>
        </button>
      ) : (
        <>
          {thread.resolved && <p className="muted">Resolved</p>}
          {thread.comments.map((c) => (
            <div key={c.id} className="thread-c">
              <p><b className="plain">{c.author}</b>{c.by_owner && <span className="tag"> Author</span>}</p>
              <p className="plain">{c.body}</p>
            </div>
          ))}
          {reply}
        </>
      )}
    </section>
  );
}

export function OutdatedList({ threads, card }: { threads: PublicThread[]; card: (t: PublicThread) => ReactNode }) {
  if (!threads.length) return null;
  return (
    <section aria-labelledby="outdated-h" className="outdated box">
      <h2 id="outdated-h">Outdated</h2>
      {threads.map((t) => (
        <div key={t.id}>
          <blockquote className="plain quote">{t.anchor.exact}</blockquote>
          {card(t)}
        </div>
      ))}
    </section>
  );
}
