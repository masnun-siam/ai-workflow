import { useState } from "preact/hooks";
import { http } from "../api/http";
import type { Dispatch, DispatchPlan, DispatchSettings, Lane } from "../api/types";
import { coordinators, dispatches, grinds, mutate, panels, runsTab, sessionList } from "../state/data";
import { runList } from "../state/select";
import { detailOpen, sel, setSel } from "../state/ui";
import { prefs } from "../state/prefs";
import { fmtCost, fmtDur, shortRepo } from "../state/format";
import { Header } from "../components/Header";
import { statusTone } from "../components/SessionView";
import { Btn, Chips, Empty, Field, Pane, Tag } from "../components/ui";

const TABS: ["sessions" | "dispatch" | "coordinators" | "grinds" | "panels", string][] = [
  ["sessions", "Sessions"], ["dispatch", "Dispatch"], ["coordinators", "Coordinators"], ["grinds", "Grinds"], ["panels", "Peer review"],
];

function Sessions() {
  const list = runList.value;
  const st = sessionList.value?.stats;
  return (
    <Pane label={`runs · ${st?.today_count ?? 0} today · ${fmtCost(st?.today_cost ?? 0)}`}>
      <div class="rows">
        {list.map((s, i) => (
          <button key={s.id} type="button" class={`row r5${i === sel.value.runs ? " sel" : ""}`} aria-current={i === sel.value.runs}
            onClick={() => { setSel({ runs: i }); if (prefs.value.layout === "drawer") detailOpen.value = true; }}>
            <span class={`tag ${statusTone(s.status)}`}>{s.status}</span>
            <span class="t mono">{s.skill ?? "free text"}</span>
            <span class="t">{s.title}</span>
            <span class="w mono">{fmtDur(s.duration_s)}</span>
            <span class="w mono">{fmtCost(s.cost)}</span>
          </button>
        ))}
        {sessionList.value && list.length === 0 && <Empty>No runs yet. Press : to start one.</Empty>}
        {!sessionList.value && <Empty>Loading…</Empty>}
      </div>
    </Pane>
  );
}

const LANE_ACTIONS: [string, string][] = [["pause", "Pause"], ["resume", "Resume"], ["retry", "Retry"], ["skip", "Skip"], ["merge", "Merge"], ["hold", "Hold merge"], ["unhold", "Release merge"]];

function LaneRow({ d, l }: { d: Dispatch; l: Lane }) {
  const go = (action: string) => mutate(() => http.send("POST", `/api/dispatches/${d.id}/lane`, { lane: l.key, action }), `${action}: ${l.key}`, ["dispatches"]);
  return (
    <tr>
      <td class="mono">{l.key}<br /><span class="dim">{l.title}</span></td>
      <td><Tag tone={l.stage === "closed" ? "c-o" : l.needs_you ? "c-w" : "c-q"}>{l.stage}</Tag>{l.paused && " paused"}</td>
      <td>{l.needs_you ?? l.held ?? l.gate ?? l.skip_reason ?? ""}{l.pr ? ` PR #${l.pr}` : ""}</td>
      <td>{fmtCost(l.usage.cost)}</td>
      <td><div class="acts">
        {l.session && <a href={`#/sessions/${l.session}`}>session</a>}
        {LANE_ACTIONS.filter(([a]) => (a === "pause" ? !l.paused : a === "resume" ? l.paused : a === "hold" ? !l.hold_merge : a === "unhold" ? l.hold_merge : true)).map(([a, t]) => <Btn small key={a} onClick={() => void go(a)}>{t}</Btn>)}
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
          {d.state === "running" ? <Btn small onClick={() => void setState("paused")}>Pause</Btn> : d.state === "paused" ? <Btn small primary onClick={() => void setState("running")}>Resume</Btn> : null}
          {(d.state === "running" || d.state === "paused") && <Btn small bad onClick={() => void setState("cancelled")}>Cancel</Btn>}
          <Btn small onClick={() => void mutate(() => http.send("POST", `/api/dispatches/${d.id}/retry-failed`, {}), "Retrying failed lanes", ["dispatches"])}>Retry failed</Btn>
          {(["open-pr", "qa", "grind-pr"] as const).map((a) => <Btn small key={a} onClick={() => void mutate(() => http.send("POST", `/api/dispatches/${d.id}/end`, { action: a }), a, ["dispatches"])}>{a}</Btn>)}
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
  const body = () => (/^[\w./-]+#\d+(\s*,\s*[\w./-]+#\d+)+$/.test(epic) ? { issues: epic.split(/\s*,\s*/) } : { epic });
  return (
    <Pane label="new dispatch">
      <form class="det" onSubmit={(e) => e.preventDefault()}>
        <Field label="Epic (owner/name#N or an epic link) or comma-separated issues"><input value={epic} onInput={(e) => setEpic((e.target as HTMLInputElement).value)} placeholder="acme/wasensi-docs#941" /></Field>
        <div class="acts">
          <Btn disabled={!epic.trim()} onClick={async () => setPlan((await mutate(() => http.send<DispatchPlan>("POST", "/api/dispatches/plan", body()), null)) ?? null)}>Plan</Btn>
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

export function Runs() {
  const tab = runsTab.value;
  return (
    <>
      <Header title="runs" />
      <Chips label="Runs view" value={tab} options={TABS} onPick={(t) => (runsTab.value = t)} />
      {tab === "sessions" && <Sessions />}
      {tab === "dispatch" && <><NewDispatch />{(dispatches.value ?? []).map((d) => <DispatchCard key={d.id} d={d} />)}{dispatches.value?.length === 0 && <Empty>No dispatches yet.</Empty>}</>}
      {tab === "coordinators" && (
        <Pane label="coordinators">
          {(coordinators.value ?? []).map((c) => (
            <div class="det" key={c.run}>
              <div class="dh"><Tag tone={c.live ? "c-q" : ""}>{c.live ? "live" : "stopped"}</Tag><b>{c.source}</b><span class="dim">{shortRepo(c.repo)} → {c.destination}</span></div>
              <div class="tablewrap"><table class="t"><tbody>{c.queue.map((q) => <tr key={q.issue}><td>#{q.issue}</td><td>{q.title}</td><td>{q.state}</td></tr>)}</tbody></table></div>
              <div class="log">{c.events.map((e, i) => <span key={i}>{e}</span>)}</div>
              <div class="acts">{c.session && <a href={`#/sessions/${c.session}`}>session</a>}<Btn small bad onClick={() => void mutate(() => http.send("POST", `/api/coordinators/${c.run}/stop`, {}), "Coordinator stopped", ["coordinators"])}>Stop refilling</Btn></div>
            </div>
          ))}
          {coordinators.value?.length === 0 && <Empty>No coordinators.</Empty>}
        </Pane>
      )}
      {tab === "grinds" && (
        <Pane label="grinds">
          <div class="tablewrap"><table class="t"><thead><tr><th>PR</th><th>State</th><th>Round</th><th>Reason</th><th /></tr></thead><tbody>
            {(grinds.value ?? []).map((g) => (
              <tr key={`${g.repo}#${g.pr}`}><td class="mono">{g.repo}#{g.pr}</td><td><Tag tone={g.state === "running" ? "c-q" : g.state === "paused" ? "c-w" : "c-o"}>{g.state}</Tag></td><td>{g.rounds}{g.mode ? ` · ${g.mode}` : ""}</td><td>{g.reason ?? ""}</td>
                <td><div class="acts">{g.session && <a href={`#/sessions/${g.session}`}>session</a>}
                  <Btn small onClick={() => void mutate(() => http.send("POST", `/api/grinds/${g.repo}/${g.pr}/skip-ci`, {}), "CI wait skipped", ["grinds"])}>Skip CI</Btn>
                  <Btn small bad onClick={() => void mutate(() => http.send("POST", `/api/grinds/${g.repo}/${g.pr}/stop`, {}), "Grind stopped", ["grinds"])}>Stop</Btn></div></td></tr>
            ))}</tbody></table></div>
          {grinds.value?.length === 0 && <Empty>No grinds.</Empty>}
        </Pane>
      )}
      {tab === "panels" && (
        <Pane label="peer review panels">
          {(panels.value ?? []).map((p) => (
            <div class="det" key={p.id}>
              <div class="dh"><Tag tone={p.state === "approved" ? "c-o" : p.state === "running" ? "c-q" : "c-w"}>{p.state}</Tag><b>{p.artifact}</b><span class="dim">round {p.round}/{p.max_rounds} · {p.status.approved}/{p.status.total} approved</span></div>
              <div class="chips">{Object.entries(p.status.lenses).map(([l, v]) => <span class="chip" key={l}>{l}: {v}</span>)}</div>
              <div class="acts">{[1, 2].map((n) => <Btn small key={n} onClick={() => void mutate(() => http.send("POST", `/api/review/${p.id}/rounds`, { add: n }), `Added ${n} round(s)`, ["panels"])}>+{n} round{n > 1 ? "s" : ""}</Btn>)}</div>
            </div>
          ))}
          {panels.value?.length === 0 && <Empty>No panels.</Empty>}
        </Pane>
      )}
    </>
  );
}
