import { useDispatch } from '../api/hooks';
import type { Dispatch } from '../api/types';
import { needsYou, secs } from '../dispatch/vocab';
import { issueBuckets, type Feature } from '../lib/features';
import { money } from '../lib/format';
import { usePanel } from '../panels/PanelContext';

/** One tile per issue in number order; the bar and the legend read the same issue buckets. */
export function BuildMap({ f, repo, dispatch }: { f: Feature; repo: string; dispatch?: Dispatch }) {
  const panel = usePanel();
  if (!f.issues.length) return null;
  const you = new Map((dispatch?.lanes ?? []).filter(needsYou).map((l) => [l.n, l]));
  const buckets = issueBuckets(f.issues, new Set(you.keys()));
  const bucket = new Map(buckets.flatMap((b) => b.items.map((i) => [i.n, b] as const)));
  return (
    <section className="pane bmap" aria-labelledby="map-h">
      <div className="bmap-h">
        <h2 id="map-h" className="sec-h">Build map</h2>
        <ul className="tile-key" aria-label="Issues by state">
          {buckets.map((b) => <li key={b.id}><i className={`s-${b.id}`} />{b.label} <span>{b.items.length}</span></li>)}
        </ul>
      </div>
      <div className="tiles">
        {[...f.issues].sort((a, b) => a.n - b.n).map((i) => {
          const b = bucket.get(i.n)!;
          const y = you.get(i.n);
          const label = `#${i.n} ${i.title}, ${b.label}`;
          const why = y?.needs_you ?? y?.held;
          return (
            <button key={i.n} type="button" className={`tile${y ? ' you' : ''}`} aria-label={label} title={why ? `${label}: ${why}` : label} onClick={() => panel.open({ kind: 'issue', repo, n: i.n })}>
              <span>#{i.n}</span>
              {y ? <small>Needs you</small> : null}
              <i className={`s-${b.id}`} />
            </button>
          );
        })}
      </div>
    </section>
  );
}

const ago = (at: number) => new Date(at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });

export function DispatchPanel({ id }: { id: string }) {
  const d = useDispatch(id).data;
  if (!d?.totals) return null;
  const events = [...(d.events ?? [])].sort((a, b) => b.at - a.at).slice(0, 5);
  const tok = d.totals.tokens >= 1e6 ? `${(d.totals.tokens / 1e6).toFixed(2)}M` : `${Math.round(d.totals.tokens / 1e3)}k`;
  return (
    <section className="pane fpanel" aria-labelledby="run-h">
      <h2 id="run-h">Dispatch{d.state === 'paused' ? ' (paused)' : ''}</h2>
      <div className="stats">
        <div><b>{secs(d.totals.seconds)}</b><span>running</span></div>
        <div><b>{money(d.totals.cost)}</b><span>spent</span></div>
        <div><b>{tok}</b><span>tokens</span></div>
      </div>
      {events.length ? (
        <ol className="stack" style={{ gap: 8, margin: 0, padding: 0, listStyle: 'none', fontSize: 13 }}>
          {events.map((e, k) => (
            <li key={k} style={{ display: 'grid', gridTemplateColumns: '44px 8px minmax(0,1fr)', gap: 10, alignItems: 'baseline' }}>
              <span className="mono muted" style={{ fontSize: 12 }}>{ago(e.at)}</span>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: e.kind === 'needs_you' || e.kind === 'held' ? 'var(--you)' : 'var(--accent)' }} />
              <span>{e.lane ? `${e.lane.replace(/^.*#/, '#')} ` : ''}{e.text}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
