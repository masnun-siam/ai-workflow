// The transcript (FR-20): events in time order, runs of tool calls folded into one expandable row, search, auto-scroll while live.
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { StreamEvent } from '../api/types';
import { Icon } from '../components';
import { mdToHtml } from '../lib/md';
import { fmtTokens, money, toolSummary } from '../lib/format';

/** Searchable text of one event. */
export function eventText(e: StreamEvent): string {
  if (e.kind === 'tool') return `${e.name} ${e.input === undefined ? '' : JSON.stringify(e.input)}`;
  return String(e.text ?? '');
}
/** Events matching `query`, each with its original index (stable keys while filtering). */
export function filterEvents(events: StreamEvent[], query: string) {
  const t = query.trim().toLowerCase();
  const all = events.map((e, i) => ({ e, i }));
  return t ? all.filter(({ e }) => eventText(e).toLowerCase().includes(t)) : all;
}

/** Drops a text event that the result right after it repeats word for word (the final message). */
export function dropEchoes(events: { e: StreamEvent; i: number }[], all: StreamEvent[]) {
  return events.filter(({ e, i }) => {
    const next = all[i + 1];
    return !(e.kind === 'text' && next?.kind === 'result' && typeof e.text === 'string' && e.text.trim() === String(next.text ?? '').trim());
  });
}

/** Tool input with worktree and repo prefixes cut, so the command itself shows. */
export function shortPaths(s: string, root?: string | null) {
  const t = s.replace(/\/\S*?\/\.worktrees\/[^/\s]+\//g, '');
  return root ? t.split(`${root.replace(/\/$/, '')}/`).join('') : t;
}

type Item = { e: StreamEvent; i: number };
/** Consecutive tool events become one group; anything else stays a single row. */
export function groupTools(items: Item[]): (Item | Item[])[] {
  const out: (Item | Item[])[] = [];
  for (const it of items) {
    const last = out[out.length - 1];
    if (it.e.kind === 'tool' && Array.isArray(last)) last.push(it);
    else out.push(it.e.kind === 'tool' ? [it] : it);
  }
  return out;
}

/** "Bash ×4, Read" for a group's label. */
export function toolCounts(g: Item[]) {
  const n = new Map<string, number>();
  for (const { e } of g) n.set(String(e.name), (n.get(String(e.name)) ?? 0) + 1);
  return [...n].map(([k, v]) => (v > 1 ? `${k} ×${v}` : k)).join(', ');
}

/** Events shown before "Show earlier events"; search always covers all of them. */
const LIMIT = 500;

/** One transcript row. Events are append-only, so memo keeps earlier rows from re-rendering (and re-running mdToHtml). */
const EventRow = memo(function EventRow({ e, i, isOpen, onToggle, root, above }: { e: StreamEvent; i: number; isOpen: boolean; onToggle: (i: number) => void; root?: string | null; above?: boolean }) {
  const html = useMemo(() => (e.kind === 'tool' ? '' : mdToHtml(e.text)), [e]);
  if (e.kind === 'tool')
    return (
      <div className="ev tool">
        <span className="ic"><Icon n="tool" s={14} /></span>
        <div className="body" style={{ minWidth: 0 }}>
          <button type="button" className="linkish mono ellipsis" style={{ display: 'block', maxWidth: '100%', color: 'var(--muted)' }} aria-expanded={isOpen} onClick={() => onToggle(i)}>
            <b style={{ color: 'var(--ink)', fontWeight: 500 }}>{String(e.name)}</b> {shortPaths(toolSummary(e.input, 400), root)}
          </button>
          {isOpen ? <pre>{e.input === undefined ? '' : JSON.stringify(e.input, null, 2)}</pre> : null}
        </div>
      </div>
    );
  if (e.kind === 'result')
    return (
      <div className={`ev result t-${e.is_error ? 'bad' : 'ship'}`}>
        <span className="ic"><Icon n={e.is_error ? 'alert' : 'check'} s={14} /></span>
        <div className="body">
          <b>{e.is_error ? 'Failed' : 'Result'}</b>
          {typeof e.cost === 'number' ? ` · ${money(e.cost)}` : ''}
          {e.tokens && typeof (e.tokens as { output?: number }).output === 'number' ? ` · ${fmtTokens(((e.tokens as { input?: number }).input ?? 0) + (e.tokens as { output: number }).output)} tok` : ''}
          {above ? <span className="muted"> · the summary is at the top</span> : null}
          {e.text && !above ? <div className="prose" dangerouslySetInnerHTML={{ __html: html }} /> : null}
        </div>
      </div>
    );
  return (
    <div className="ev text">
      <span className="ic"><Icon n="msg" s={14} /></span>
      <div className="body prose" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
});

/** `root` is cut from tool paths; `summaryAbove` is the index of the result the page shows above the transcript. */
export function Transcript({ events, live, working, root, summaryAbove }: { events: StreamEvent[]; live: boolean; working: boolean; root?: string | null; summaryAbove?: number }) {
  const [q, setQ] = useState('');
  const [follow, setFollow] = useState(true);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [all, setAll] = useState(false);
  const [flat, setFlat] = useState(false);
  const [atEnd, setAtEnd] = useState(true);
  const end = useRef<HTMLDivElement>(null);
  const shown = dropEchoes(filterEvents(events, q), events);
  const more = !q.trim() && !all && shown.length > LIMIT;
  const visible = more ? shown.slice(-LIMIT) : shown;
  const rows = flat || q.trim() ? visible : groupTools(visible);
  const toggle = useCallback((i: number) => setOpen((o) => ({ ...o, [i]: !o[i] })), []);
  useEffect(() => {
    if (live && follow) end.current?.scrollIntoView({ block: 'nearest' });
  }, [events.length, live, follow]);
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined' || !end.current) return;
    const io = new IntersectionObserver(([en]) => setAtEnd(en.isIntersecting));
    io.observe(end.current);
    return () => io.disconnect();
  }, []);
  const jump = () => {
    setFollow(true);
    end.current?.scrollIntoView({ block: 'nearest' });
  };
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row wrap">
        <h2>How it got there</h2>
        <div className="seg" role="radiogroup" aria-label="Transcript view">
          <button type="button" role="radio" aria-checked={!flat} className={flat ? '' : 'on'} onClick={() => setFlat(false)}>Story</button>
          <button type="button" role="radio" aria-checked={flat} className={flat ? 'on' : ''} onClick={() => setFlat(true)}>All steps</button>
        </div>
        <span className="grow" />
        <input className="f" style={{ maxWidth: 220 }} placeholder="Search the transcript" aria-label="Search the transcript" value={q} onChange={(e) => setQ(e.target.value)} />
        {q ? <span className="muted" style={{ fontSize: 13 }}>{shown.length} of {events.length}</span> : null}
        {live ? <label className="row" style={{ gap: 6, fontSize: 13 }}><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />Auto-scroll</label> : null}
      </div>
      <div className="events" aria-label="Transcript">
        {!events.length ? <p className="muted" style={{ padding: 10 }}>Nothing yet. Events appear here as Claude works.</p> : null}
        {events.length > 0 && !shown.length ? <p className="muted" style={{ padding: 10 }}>No events match.</p> : null}
        {more ? <button type="button" className="btn" onClick={() => setAll(true)}>Show earlier events ({shown.length - LIMIT})</button> : null}
        {rows.map((r) => {
          const row = ({ e, i }: Item) => <EventRow key={i} e={e} i={i} isOpen={!!open[i]} onToggle={toggle} root={root} above={i === summaryAbove} />;
          if (!Array.isArray(r)) return row(r);
          if (r.length === 1) return row(r[0]);
          const k = -1 - r[0].i; // groups share `open` with rows, on negative keys
          return (
            <div key={k} className="ev-group">
              <button type="button" className="ev tool linkish" aria-expanded={!!open[k]} onClick={() => toggle(k)}>
                <span className="ic"><Icon n={open[k] ? 'down' : 'right'} s={14} /></span>
                <span className="body ellipsis"><b>{r.length} steps</b> · {toolCounts(r)}</span>
              </button>
              {open[k] ? <div className="ev-steps">{r.map(row)}</div> : null}
            </div>
          );
        })}
        {working ? <div className="ev"><span className="ic"><span className="chip t-build live" style={{ padding: 0, background: 'none' }}><span className="dot" /></span></span><div className="muted">Working…</div></div> : null}
        <div ref={end} />
      </div>
      {live && !atEnd ? <button type="button" className="btn sm" style={{ position: 'sticky', bottom: 12, alignSelf: 'center' }} onClick={jump}>Jump to latest</button> : null}
    </div>
  );
}
