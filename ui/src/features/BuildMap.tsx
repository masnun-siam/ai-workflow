import type { CSSProperties } from 'react';
import { useDispatch } from '../api/hooks';
import type { Dispatch } from '../api/types';
import { Icon } from '../components';
import { levels, needsYou, secs } from '../dispatch/vocab';
import { countBy, type Feature, type FeatureIssue } from '../lib/features';
import { money } from '../lib/format';
import { ISSUE, STAGES, stageIdx } from '../lib/vocab';
import { usePanel } from '../panels/PanelContext';

/** The six stages as filled blocks: done ones in their stage tint, the current one deep, the rest dashed. */
export function StageStrip({ f }: { f: Feature }) {
  const at = stageIdx(f.stage);
  const c = countBy(f.issues);
  const fact = (id: string, k: number) =>
    k > at ? '' : id === 'tasks' ? `${f.issues.length} issues` : id === 'building' ? `${c.merged ?? 0} of ${f.issues.length} merged` : k < at ? 'done' : 'now';
  return (
    <ol className="stages" aria-label="Stages">
      {STAGES.map((s, k) => (
        <li key={s.id} className={k < at ? 'done' : k === at ? 'now' : 'todo'} style={{ '--st': `var(--st${k})`, color: k <= at && k >= 3 ? 'var(--st4-ink)' : undefined } as CSSProperties} aria-current={k === at ? 'step' : undefined}>
          <b>{s.label}</b>
          <span>{fact(s.id, k)}</span>
        </li>
      ))}
    </ol>
  );
}

/** Build waves: an issue sits one column after the latest issue it waits on. A dispatch's lanes carry the
 * full dependency list; without one, the board's open blockers are all there is. */
function waves(issues: FeatureIssue[], d: Dispatch | undefined): FeatureIssue[][] {
  let depth: Record<number, number> = {};
  if (d) {
    const lv = levels(d.lanes);
    for (const l of d.lanes) depth[l.n] = lv[l.key] ?? 0;
  } else {
    const by = new Map(issues.map((i) => [i.n, i]));
    const walk = (n: number, seen: Set<number>): number => {
      if (depth[n] !== undefined) return depth[n];
      if (seen.has(n)) return 0;
      seen.add(n);
      const deps = (by.get(n)?.blocked_by ?? []).filter((b) => by.has(b));
      return (depth[n] = deps.length ? 1 + Math.max(...deps.map((b) => walk(b, seen))) : 0);
    };
    depth = {};
    for (const i of issues) walk(i.n, new Set());
  }
  const out: FeatureIssue[][] = [];
  for (const i of [...issues].sort((a, b) => a.n - b.n)) (out[depth[i.n] ?? 0] ??= []).push(i);
  return out.filter(Boolean);
}

const waveLabel = (k: number, w: FeatureIssue[], issues: FeatureIssue[]) => {
  if (k === 0) return 'Starts first';
  const deps = [...new Set(w.flatMap((i) => i.blocked_by))].filter((n) => issues.some((x) => x.n === n));
  return deps.length && deps.length <= 4 ? `After ${deps.map((n) => `#${n}`).join(', ')}` : 'Then';
};

export function BuildMap({ f, repo, dispatch }: { f: Feature; repo: string; dispatch?: Dispatch }) {
  const panel = usePanel();
  if (!f.issues.length) return null;
  const you = new Map((dispatch?.lanes ?? []).filter(needsYou).map((l) => [l.n, l]));
  const cols = waves(f.issues, dispatch);
  const merged = countBy(f.issues).merged ?? 0;
  return (
    <section className="pane bmap" aria-labelledby="map-h">
      <div className="bmap-h">
        <h2 id="map-h" className="sec-h">Build map</h2>
        <p>Issues run left to right; each column waits on one before it.</p>
        <b>{merged}<small>/{f.issues.length} merged</small></b>
      </div>
      <div className="waves">
        {cols.map((w, k) => (
          <div key={k} className="row" style={{ gap: 10, alignItems: 'stretch', flex: k === 0 ? '1.3 0 240px' : '1 0 220px', minWidth: 0 }}>
            {k ? <div className="wave-arrow" aria-hidden="true"><Icon n="right" s={18} /></div> : null}
            <div className="wave">
              <span>{waveLabel(k, w, f.issues)}</span>
              {w.map((i) => {
                const y = you.get(i.n);
                const cls = y ? 'you' : i.status === 'merged' ? 'merged' : ['in_progress', 'draft_pr', 'in_review', 'grinding'].includes(i.status) ? 'active' : '';
                return (
                  <button key={i.n} type="button" className={`node ${cls}`} onClick={() => panel.open({ kind: 'issue', repo, n: i.n })} title={y?.needs_you ?? y?.held ?? undefined}>
                    <span className="nt"><span>#{i.n}</span><span>{y ? 'Needs you' : ISSUE[i.status].label}</span></span>
                    <span className="nn">{i.title}</span>
                    {i.pr ? <span className="np">PR #{i.pr.n}</span> : i.status === 'merged' ? null : <span className="np">No PR yet</span>}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
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
