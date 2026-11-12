import { useState } from "preact/hooks";
import { http } from "../api/http";
import type { Dispatch, DispatchPlan, DispatchSettings, Lane } from "../api/types";
import { currentRepo, dispatches, mutate } from "../state/data";
import { dispatchList } from "../state/select";
import { askConfirm } from "../state/ui";
import { fmtCost } from "../state/format";
import { Header } from "../components/Header";
import { Btn, Chips, Empty, Field, Pane, Tag } from "../components/ui";

const END_ACTIONS: [string, string][] = [["open-pr", "Open PR"], ["qa", "QA"], ["grind-pr", "Grind PR"]];
const LANE_ACTIONS: [string, string][] = [["pause", "Pause"], ["resume", "Resume"], ["retry", "Retry"], ["skip", "Skip"], ["merge", "Merge"], ["hold", "Hold merge"], ["unhold", "Release merge"]];

function LaneRow({ d, l }: { d: Dispatch; l: Lane }) {
  const go = async (action: string) => {
    if ((action === "merge" || action === "skip") && !(await askConfirm(action === "merge" ? `Merge the PR for ${l.key} now?` : `Skip ${l.key}? It will not be worked on in this dispatch.`))) return;
    return mutate(() => http.send("POST", `/api/dispatches/${d.id}/lane`, { lane: l.key, action }), `${action}: ${l.key}`, ["dispatches"]);
  };
  return (
    <tr>
      <td class="mono">{l.key}<br /><span class="dim">{l.title}</span></td>
      <td><Tag tone={l.stage === "closed" ? "c-o" : l.needs_you ? "c-w" : "c-q"}>{l.stage}</Tag>{l.paused && " paused"}</td>
      <td>{l.needs_you ?? l.held ?? l.gate ?? l.skip_reason ?? ""}{l.pr ? ` PR #${l.pr}` : ""}</td>
      <td>{fmtCost(l.usage.cost)}</td>
      <td><div class="acts">
        {l.session && <a href={`#/sessions/${l.session}`}>session</a>}
        {LANE_ACTIONS.filter(([a]) => (a === "pause" ? !l.paused : a === "resume" ? l.paused : a === "hold" ? !l.hold_merge : a === "unhold" ? l.hold_merge : true)).map(([a, t]) => <Btn small key={a} onClick={() => go(a)}>{t}</Btn>)}
      </div></td>
    </tr>
  );
}

function DispatchCard({ d }: { d: Dispatch }) {
  const setState = (state: string) => mutate(() => http.send("POST", `/api/dispatches/${d.id}/state`, { state }), `Dispatch ${state}`, ["dispatches"]);
  const setSetting = (patch: Partial<DispatchSettings>) => mutate(() => http.send("POST", `/api/dispatches/${d.id}/settings`, patch), "Saved", ["dispatches"]);
  return (
    <Pane label={`dispatch · ${d.title} · ${d.state}`}>
      <div class="det">
        <span class="dim">{d.totals.closed}/{d.totals.lanes} closed · {fmtCost(d.totals.cost)}</span>
        <div class="acts">
          {d.state === "running" ? <Btn small onClick={() => setState("paused")}>Pause</Btn> : d.state === "paused" ? <Btn small primary onClick={() => setState("running")}>Resume</Btn> : null}
          {(d.state === "running" || d.state === "paused") && <Btn small bad onClick={async () => { if (await askConfirm(`Cancel dispatch ${d.title}? Running lanes stop.`)) await setState("cancelled"); }}>Cancel dispatch</Btn>}
          <Btn small onClick={() => mutate(() => http.send("POST", `/api/dispatches/${d.id}/retry-failed`, {}), "Retrying failed lanes", ["dispatches"])}>Retry failed</Btn>
          {END_ACTIONS.map(([a, t]) => <Btn small key={a} onClick={() => mutate(() => http.send("POST", `/api/dispatches/${d.id}/end`, { action: a }), `${t}: started`, ["dispatches"])}>{t}</Btn>)}
        </div>
        <div class="fields">
          <Field label="Parallel lanes"><input type="number" min={1} max={8} value={d.settings.max} onChange={(e) => void setSetting({ max: Number((e.target as HTMLInputElement).value) })} /></Field>
          <Field label="Grind"><select value={d.settings.grind} onChange={(e) => void setSetting({ grind: (e.target as HTMLSelectElement).value as DispatchSettings["grind"] })}><option>off</option><option>simple</option><option>full</option></select></Field>
          <Field label="CI"><select value={d.settings.ci} onChange={(e) => void setSetting({ ci: (e.target as HTMLSelectElement).value as DispatchSettings["ci"] })}><option>wait</option><option>defer</option><option>ignore</option></select></Field>
          <label class="fld"><span>Auto merge</span><input type="checkbox" checked={d.settings.auto_merge} onChange={(e) => void setSetting({ auto_merge: (e.target as HTMLInputElement).checked })} /></label>
        </div>
        <div class="tablewrap"><table class="t"><thead><tr><th>Lane</th><th>Stage</th><th>Detail</th><th>Cost</th><th /></tr></thead>
          <tbody>{d.lanes.map((l) => <LaneRow key={l.key} d={d} l={l} />)}</tbody></table></div>
      </div>
    </Pane>
  );
}

function NewDispatch() {
  const [epic, setEpic] = useState("");
  const [plan, setPlan] = useState<DispatchPlan | null>(null);
  const plan_ = async () => setPlan((await mutate(() => http.send<DispatchPlan>("POST", "/api/dispatches/plan", body()), null)) ?? null);
  const body = () => {
    const v = /^#?\d+$/.test(epic.trim()) && currentRepo.value ? `${currentRepo.value}#${epic.trim().replace("#", "")}` : epic.trim();
    return /^[\w./-]+#\d+(\s*,\s*[\w./-]+#\d+)+$/.test(v) ? { issues: v.split(/\s*,\s*/) } : { epic: v };
  };
  return (
    <Pane label="new dispatch">
      <form class="det" onSubmit={async (e) => { e.preventDefault(); if (epic.trim()) await plan_(); }}>
        <Field label="Epic (owner/name#N, #N in the current repo, or an epic link) or comma-separated issues"><input value={epic} onInput={(e) => setEpic((e.target as HTMLInputElement).value)} placeholder={`${currentRepo.value ?? "owner/name"}#123`} /></Field>
        <div class="acts">
          <Btn type="submit" disabled={!epic.trim()}>Plan</Btn>
          <Btn primary disabled={!epic.trim()} onClick={async () => { if (await mutate(() => http.send("POST", "/api/dispatches", body()), "Dispatch started", ["dispatches"])) { setPlan(null); setEpic(""); } }}>Start</Btn>
        </div>
        {plan && (
          <div><b>{plan.title}</b>
            {plan.waves.map((w, i) => <div key={i} class="mono">wave {i + 1}: {w.join(", ")}</div>)}
            {plan.warnings.map((w) => <div class="c-w" key={w}>{w}</div>)}</div>
        )}
      </form>
    </Pane>
  );
}

type Tab = "all" | "needs" | "live" | "done";
const TABS: [Tab, string][] = [["all", "All"], ["needs", "Needs you"], ["live", "Live"], ["done", "Finished"]];
const inTab = (d: Dispatch, t: Tab) =>
  t === "all" || (t === "needs" ? d.lanes.some((l) => l.needs_you) : t === "live" ? d.state === "running" || d.state === "paused" : d.state === "done" || d.state === "cancelled");

export function Dispatches() {
  const [tab, setTab] = useState<Tab>("all");
  const [showNew, setShowNew] = useState(false);
  const list = dispatchList.value.filter((d) => inTab(d, tab));
  return (
    <>
      <Header title="Dispatches" scope sub={`${dispatchList.value.filter((d) => d.state === "running").length} running`}>
        <Btn primary onClick={() => setShowNew(!showNew)}>{showNew ? "Close" : "Run an epic"}</Btn>
      </Header>
      {showNew && <NewDispatch />}
      <Chips label="Dispatch filter" value={tab} options={TABS} onPick={setTab} />
      {list.map((d) => <DispatchCard key={d.id} d={d} />)}
      {dispatches.value && list.length === 0 && <Empty>{dispatchList.value.length ? "No dispatch in this view." : "No dispatches yet. Run an epic to start one."}</Empty>}
      {!dispatches.value && <Empty>Loading…</Empty>}
    </>
  );
}
