/** Small changes (old aiw): issues that belong to no epic. Where they stand, Ready to run (pick and run
 *  as a dispatch), Needs refining, and every issue with a filter. Filing one is the small-change step. */
import { useEffect, useState } from "preact/hooks";
import type { FeatureIssue, FeatureIssueState } from "../api/types";
import { changes, loadErrors } from "../state/data";
import { exec } from "../state/exec";
import { ago, prio, shortRepo } from "../state/format";
import { nav } from "../state/route";
import { openCreate } from "../state/ui";
import { Header } from "../components/Header";
import { Btn, Empty, Pane, Tag } from "../components/ui";

const COLS: [string, FeatureIssueState[]][] = [
  ["Needs refining", ["unrefined"]], ["Ready", ["ready"]], ["Blocked", ["blocked"]], ["In flight", ["in_progress", "dispatch"]],
  ["In review", ["in_review", "mergeable", "conflict", "ci_failed"]], ["Needs you", ["waiting", "failed"]],
];
const PRIOS = ["P0", "P1", "P2", "P3"];
const prioOf = (i: FeatureIssue) => prio(i.priority) || "—";
/** Rows each section renders before "show more": 1,000+ issues must not become 1,000 DOM rows. */
export const CAP = 50;
/** The most issues one dispatch takes. */
const MAX_PICK = 30;
const LABEL: Record<FeatureIssueState, string> = {
  unrefined: "Needs refining", ready: "Ready", blocked: "Blocked", in_progress: "Running", dispatch: "In dispatch", in_review: "In review", mergeable: "Ready to merge",
  conflict: "Conflict", ci_failed: "CI failed", waiting: "Needs you", failed: "Failed",
};
const TONE: Partial<Record<FeatureIssueState, string>> = { unrefined: "c-w", ready: "c-o", mergeable: "c-o", in_progress: "c-q", dispatch: "c-q", in_review: "c-q", conflict: "c-b", ci_failed: "c-b", failed: "c-b", waiting: "c-w" };

function Row({ i, pick }: { i: FeatureIssue; pick?: { on: boolean; set: (v: boolean) => void } }) {
  return (
    <div class="irow">
      {pick ? <input type="checkbox" aria-label={`Pick ${i.key}`} checked={pick.on} onChange={(e) => pick.set((e.target as HTMLInputElement).checked)} /> : <span />}
      <Tag tone={TONE[i.state]}>{LABEL[i.state]}</Tag>
      <span class="t"><a href={i.url} class="mono" target="_blank" rel="noreferrer">{shortRepo(i.repo)}#{i.n}</a> {i.bug && <span class="tag c-b">bug</span>} {i.title}{prioOf(i) !== "—" && <span class="dim"> · {prioOf(i)}</span>}
        {i.state === "blocked" && <span class="dim"> · after {i.blockers.join(", ")}</span>}{i.pr && <> · <a href={i.pr.url} target="_blank" rel="noreferrer">PR #{i.pr.n}</a></>}</span>
      <div class="acts">{i.session && <a href={`#/sessions/${i.session}`}>session</a>}{i.actions.map((a) => <Btn key={a.label} small primary={a.primary} onClick={() => exec(a)}>{a.label}</Btn>)}</div>
    </div>
  );
}

/** The first `CAP` rows of a section, with a control for the rest. */
function Capped({ rows, render }: { rows: FeatureIssue[]; render: (i: FeatureIssue) => preact.ComponentChildren }) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, CAP);
  return (
    <>
      {shown.map(render)}
      {rows.length > CAP && <div class="acts"><Btn small onClick={() => setAll(!all)}>{all ? `Show first ${CAP}` : `Show all ${rows.length} (${rows.length - CAP} more)`}</Btn></div>}
    </>
  );
}

export function Changes() {
  const c = changes.value;
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [q, setQ] = useState("");
  const list = c?.issues ?? [];
  const ready = list.filter((i) => i.state === "ready");
  const unrefined = list.filter((i) => i.state === "unrefined");
  const pickedReady = ready.filter((i) => picked.has(i.key));
  // Keys that left the list on a refetch are dropped, so "Run N" never counts a ghost.
  useEffect(() => {
    if (!c || ![...picked].some((k) => !ready.some((i) => i.key === k))) return;
    setPicked(new Set([...picked].filter((k) => ready.some((i) => i.key === k))));
  }, [c]);
  const set = (k: string, v: boolean) => { const s = new Set(picked); if (v) s.add(k); else s.delete(k); setPicked(s); };
  const s = q.trim().toLowerCase();
  // The all-issues list holds what the two sections above do not, so no issue shows twice.
  const all = list.filter((i) => i.state !== "ready" && i.state !== "unrefined" && (!s || `${i.repo}#${i.n} ${i.title} ${LABEL[i.state]}`.toLowerCase().includes(s)));
  const buckets = [...PRIOS, "—"].filter((p) => list.some((i) => prioOf(i) === p));
  const err = loadErrors.value.changes;
  return (
    <>
      <Header title="Small changes" scope sub={c ? `${list.length} open without an epic · ${ready.length} ready · ${unrefined.length} to refine` : undefined}>
        <Btn primary onClick={() => openCreate()}>File a small change</Btn>
      </Header>
      {err && <div class="banner bad" role="alert">{err}</div>}
      {c && c.stale.length > 0 && <div class="banner">GitHub data is still loading or stale for {c.stale.map(shortRepo).join(", ")}.</div>}
      {!c && <Empty>Loading…</Empty>}
      {c && c.pending.length > 0 && (
        <Pane label="being filed">
          {c.pending.map((p) => <a key={p.id} class="row" href={`#/sessions/${p.id}`}><span class="tag c-q">{p.status}</span><span class="t">{p.title}</span><span class="w">{ago(p.started_at)}</span></a>)}
        </Pane>
      )}
      {c && list.length > 0 && buckets.length > 1 && (
        <Pane label="where they stand">
          <div class="tablewrap"><table class="t matrix"><thead><tr><th scope="col">Priority</th>{COLS.map(([n]) => <th scope="col" key={n}>{n}</th>)}</tr></thead><tbody>
            {[...PRIOS, "—"].map((p) => {
              const rows = list.filter((i) => prioOf(i) === p);
              if (!rows.length) return null;
              return <tr key={p}><th scope="row"><b>{p === "—" ? "none" : p}</b></th>{COLS.map(([n, st]) => { const k = rows.filter((i) => st.includes(i.state)).length; return <td key={n} class={k ? "" : "dim"}>{k || "·"}</td>; })}</tr>;
            })}
          </tbody></table></div>
        </Pane>
      )}
      {c && (
        <Pane label={`ready to run · ${ready.length}`}>
          {ready.length ? (
            <>
              <div class="acts">
                <Btn small primary disabled={!pickedReady.length || pickedReady.length > MAX_PICK} onClick={() => nav(`#/dispatches?new=${encodeURIComponent(pickedReady.map((i) => i.key).join(", "))}`)}>{pickedReady.length ? `Run ${pickedReady.length} as a dispatch` : "Run as a dispatch"}</Btn>
                <Btn small onClick={() => setPicked(new Set(ready.slice(0, MAX_PICK).map((i) => i.key)))}>{ready.length > MAX_PICK ? `Pick first ${MAX_PICK} of ${ready.length}` : `Pick all ${ready.length}`}</Btn>
                {picked.size > 0 && <Btn small onClick={() => setPicked(new Set())}>Clear</Btn>}
                <span class="dim">1–30 issues, no feature branch</span>
              </div>
              <Capped rows={ready} render={(i) => <Row key={i.key} i={i} pick={{ on: picked.has(i.key), set: (v) => set(i.key, v) }} />} />
            </>
          ) : <Empty>Nothing ready. Refine an issue below, or file a new small change.</Empty>}
        </Pane>
      )}
      {c && unrefined.length > 0 && <Pane label={`needs refining first · ${unrefined.length}`}><Capped rows={unrefined} render={(i) => <Row key={i.key} i={i} />} /></Pane>}
      {c && list.length > 0 && (
        <Pane label={`other issues · ${list.length - ready.length - unrefined.length}`}>
          <div class="filters"><input type="search" placeholder="Filter by repo, number, title or state" aria-label="Filter issues" value={q} onInput={(e) => setQ((e.target as HTMLInputElement).value)} /></div>
          <Capped key={s} rows={all} render={(i) => <Row key={i.key} i={i} />} />
          {!all.length && <Empty>No issue matches.</Empty>}
        </Pane>
      )}
      {c && !list.length && !c.pending.length && <Empty>No open issue outside an epic. File a small change to add one.</Empty>}
    </>
  );
}
