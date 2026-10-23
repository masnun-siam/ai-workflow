// The transcript (FR-20): events in time order, tool calls on one line and expandable, search, auto-scroll while live.
import { useEffect, useRef, useState } from 'react';
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

export function Transcript({ events, live, working }: { events: StreamEvent[]; live: boolean; working: boolean }) {
  const [q, setQ] = useState('');
  const [follow, setFollow] = useState(true);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const end = useRef<HTMLDivElement>(null);
  const shown = filterEvents(events, q);
  useEffect(() => {
    if (live && follow) end.current?.scrollIntoView({ block: 'nearest' });
  }, [events.length, live, follow]);
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row wrap">
        <input className="f" style={{ maxWidth: 260 }} placeholder="Search the transcript" aria-label="Search the transcript" value={q} onChange={(e) => setQ(e.target.value)} />
        {q ? <span className="muted" style={{ fontSize: 13 }}>{shown.length} of {events.length}</span> : null}
        <span className="grow" />
        {live ? <label className="row" style={{ gap: 6, fontSize: 13 }}><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />Auto-scroll</label> : null}
      </div>
      <div className="events" aria-label="Transcript">
        {!events.length ? <p className="muted" style={{ padding: 10 }}>Nothing yet. Events appear here as Claude works.</p> : null}
        {events.length > 0 && !shown.length ? <p className="muted" style={{ padding: 10 }}>No events match.</p> : null}
        {shown.map(({ e, i }) =>
          e.kind === 'tool' ? (
            <div key={i} className="ev tool">
              <span className="ic"><Icon n="tool" s={14} /></span>
              <div className="body" style={{ minWidth: 0 }}>
                <button type="button" className="linkish mono ellipsis" style={{ display: 'block', maxWidth: '100%', color: 'var(--muted)' }} aria-expanded={!!open[i]} onClick={() => setOpen((o) => ({ ...o, [i]: !o[i] }))}>
                  <b style={{ color: 'var(--ink)', fontWeight: 500 }}>{String(e.name)}</b> {toolSummary(e.input)}
                </button>
                {open[i] ? <pre>{e.input === undefined ? '' : JSON.stringify(e.input, null, 2)}</pre> : null}
              </div>
            </div>
          ) : e.kind === 'result' ? (
            <div key={i} className={`ev result t-${e.is_error ? 'bad' : 'ship'}`}>
              <span className="ic"><Icon n={e.is_error ? 'alert' : 'check'} s={14} /></span>
              <div className="body">
                <b>{e.is_error ? 'Failed' : 'Result'}</b>
                {typeof e.cost === 'number' ? ` · ${money(e.cost)}` : ''}
                {e.tokens && typeof (e.tokens as { output?: number }).output === 'number' ? ` · ${fmtTokens(((e.tokens as { input?: number }).input ?? 0) + (e.tokens as { output: number }).output)} tok` : ''}
                {e.text ? <div className="prose" dangerouslySetInnerHTML={{ __html: mdToHtml(e.text) }} /> : null}
              </div>
            </div>
          ) : (
            <div key={i} className="ev text">
              <span className="ic"><Icon n="msg" s={14} /></span>
              <div className="body prose" dangerouslySetInnerHTML={{ __html: mdToHtml(e.text) }} />
            </div>
          ),
        )}
        {working ? <div className="ev"><span className="ic"><span className="chip t-build live" style={{ padding: 0, background: 'none' }}><span className="dot" /></span></span><div className="muted">Working…</div></div> : null}
        <div ref={end} />
      </div>
    </div>
  );
}
