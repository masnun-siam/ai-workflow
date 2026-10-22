// The lanes of a dispatch as a dependency graph (columns by depth, edges drawn over) or as a table.
import { useLayoutEffect, useRef, useState } from 'react';
import type { Lane } from '../api/types';
import { Chip, Icon } from '../components';
import { shortRepo } from '../lib/format';
import { ACTIVE, STAGE, STEPS, issueNo, levels, nowLine, secs } from './vocab';

function LaneCard({ l, lanes, on, onPick, dim, multi }: { l: Lane; lanes: Lane[]; on: boolean; onPick: () => void; dim: boolean; multi: boolean }) {
  const st = STAGE[l.stage];
  const now = nowLine(l, lanes);
  const working = ACTIVE.includes(l.stage) && !now.ask && !l.paused;
  return (
    <button
      type="button"
      data-lane={l.key}
      className={`dsp-node${on ? ' on' : ''}${now.ask ? ' you' : ''}${dim ? ' dim' : ''}${l.stage === 'closed' ? ' done' : ''}`}
      onClick={onPick}
      aria-pressed={on}
    >
      <div className="row" style={{ gap: 6 }}>
        <span className="dsp-ref">{issueNo(l.key)}</span>
        {multi ? <span className="dsp-repo" title={l.repo}>{shortRepo(l.repo)}</span> : <span className="grow" />}
        <Chip tone={st.tone} live={working}>{st.label}</Chip>
      </div>
      <div className="dsp-node-t">{l.title || issueNo(l.key)}</div>
      <div className={`dsp-now t-${now.tone}`}>{now.ask ? <Icon n="alert" s={12} /> : null}{now.text}</div>
    </button>
  );
}

/** Columns by dependency depth; SVG edges from each dependency to its dependent, measured after layout. */
export function LaneGraph({ lanes, picked, onPick }: { lanes: Lane[]; picked: string | null; onPick: (k: string) => void }) {
  const lv = levels(lanes);
  const multi = new Set(lanes.map((l) => l.repo)).size > 1;
  const cols: Lane[][] = [];
  for (const l of lanes) (cols[lv[l.key]] ??= []).push(l);
  const box = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState<{ d: string; hot: boolean; done: boolean }[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const keys = lanes.map((l) => `${l.key}:${l.stage}:${l.deps.join(',')}`).join('|');

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    const draw = () => {
      const o = el.getBoundingClientRect();
      const at = (k: string) => el.querySelector<HTMLElement>(`[data-lane="${CSS.escape(k)}"]`)?.getBoundingClientRect();
      const out: { d: string; hot: boolean; done: boolean }[] = [];
      for (const l of lanes) {
        const to = at(l.key);
        for (const dep of l.deps) {
          const from = at(dep);
          if (!from || !to) continue;
          const x1 = from.right - o.left + el.scrollLeft, y1 = from.top + from.height / 2 - o.top;
          const x2 = to.left - o.left + el.scrollLeft, y2 = to.top + to.height / 2 - o.top;
          const mx = (x1 + x2) / 2;
          const src = lanes.find((x) => x.key === dep);
          out.push({ d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, hot: picked === l.key || picked === dep, done: src?.stage === 'closed' });
        }
      }
      setEdges(out);
      setSize({ w: el.scrollWidth, h: el.scrollHeight });
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(el);
    return () => ro.disconnect();
  }, [keys, picked]); // eslint-disable-line react-hooks/exhaustive-deps

  const related = picked ? new Set([picked, ...(lanes.find((l) => l.key === picked)?.deps ?? []), ...lanes.filter((l) => l.deps.includes(picked)).map((l) => l.key)]) : null;
  return (
    <div className="dsp-graph" ref={box} role="group" aria-label="Lanes by dependency">
      <svg className="dsp-edges" width={size.w} height={size.h} aria-hidden="true">
        <defs>
          <marker id="dsp-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L8,4 L0,8 z" fill="context-stroke" />
          </marker>
        </defs>
        {edges.map((e, i) => <path key={i} d={e.d} className={`${e.hot ? 'hot' : ''}${e.done ? ' done' : ''}`} markerEnd="url(#dsp-arrow)" />)}
      </svg>
      {cols.map((c, i) => (
        <div key={i} className="dsp-col">
          <div className="dsp-col-h">{i === 0 ? 'Starts first' : i === 1 ? 'Then' : 'And then'}</div>
          {c.map((l) => <LaneCard key={l.key} l={l} lanes={lanes} multi={multi} on={picked === l.key} onPick={() => onPick(l.key)} dim={!!related && !related.has(l.key)} />)}
        </div>
      ))}
    </div>
  );
}

function Progress({ l }: { l: Lane }) {
  const step = STAGE[l.stage].step;
  return (
    <div className="dsp-prog" role="img" aria-label={`${STAGE[l.stage].label}, step ${Math.max(step, 0)} of ${STEPS.length}`}>
      {STEPS.map((s, i) => <i key={s} title={s} className={i + 1 < step || l.stage === 'closed' ? 'done' : i + 1 === step ? 'now' : ''} />)}
    </div>
  );
}

export function LaneTable({ lanes, picked, onPick }: { lanes: Lane[]; picked: string | null; onPick: (k: string) => void }) {
  const multi = new Set(lanes.map((l) => l.repo)).size > 1;
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr><th>Issue</th><th>Stage</th><th>Progress</th><th>Now</th><th>PR</th><th>Time</th></tr>
        </thead>
        <tbody>
          {lanes.map((l) => {
            const now = nowLine(l, lanes);
            return (
              <tr key={l.key} className={picked === l.key ? 'on' : ''} style={{ cursor: 'pointer' }} onClick={() => onPick(l.key)}>
                <td className="title">
                  <button type="button" className="linkish" onClick={(e) => { e.stopPropagation(); onPick(l.key); }}>
                    <span className="dsp-ref">{issueNo(l.key)}</span> {l.title}
                  </button>
                  {multi ? <div className="faint" style={{ fontSize: 12 }}>{shortRepo(l.repo)}</div> : null}
                </td>
                <td><Chip tone={STAGE[l.stage].tone}>{STAGE[l.stage].label}</Chip></td>
                <td><Progress l={l} /></td>
                <td><span className={`dsp-c t-${now.tone}`}>{now.text}</span></td>
                <td>{l.pr ? `#${l.pr}` : <span className="faint">—</span>}</td>
                <td className="mono">{l.usage.seconds ? secs(l.usage.seconds) : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
