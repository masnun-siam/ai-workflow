import { http } from "../api/http";
import { activityTab, coordinators, grinds, inScope, mutate, panels, sessionList, type ActivityTab } from "../state/data";
import { activityQuery, activityResult, RUNNING, runList } from "../state/select";
import { askConfirm, detailOpen, sel, setSel } from "../state/ui";
import { prefs } from "../state/prefs";
import { ago, fmtCost, fmtDur, shortRepo } from "../state/format";
import { Header } from "../components/Header";
import { statusTone } from "../components/SessionView";
import { Btn, Chips, Empty, Pane, Tag } from "../components/ui";

const TABS: [ActivityTab, string][] = [["sessions", "Sessions"], ["coordinators", "Coordinators"], ["grinds", "Grinds"], ["panels", "Peer review"]];
const RESULTS: ["all" | "done" | "failed" | "stopped", string][] = [["all", "All"], ["done", "Done"], ["failed", "Failed"], ["stopped", "Stopped"]];

/** Live sessions as cards, like the old Activity grid. */
function Live() {
  const live = (sessionList.value?.sessions ?? []).filter((s) => inScope(s.repo) && (RUNNING.has(s.status) || s.status === "limited" || s.status === "queued"));
  if (!live.length) return null;
  return (
    <Pane label={`live · ${live.length}`}>
      <div class="live-grid">
        {live.map((s) => (
          <a key={s.id} class="live-card" href={`#/sessions/${s.id}`}>
            <span><Tag tone={statusTone(s.status)}>{s.status}</Tag> <span class="dim mono">{s.skill ?? "free text"}</span></span>
            <b class="t">{s.title}</b>
            <span class="dim">{shortRepo(s.repo)} · {fmtDur(s.duration_s)}{s.cost != null ? ` · ${fmtCost(s.cost)}` : ""}</span>
            {s.status === "limited" && s.limit_resets_at && <span class="c-w">limited, resumes {ago(new Date(s.limit_resets_at * 1000).toISOString())}</span>}
          </a>
        ))}
      </div>
    </Pane>
  );
}

function Sessions() {
  const list = runList.value;
  const st = sessionList.value?.stats;
  return (
    <Pane label={`history · ${list.length} shown · ${st?.today_count ?? 0} today`}>
      <div class="filters">
        <input type="search" placeholder="Search runs" aria-label="Search runs" value={activityQuery.value} onInput={(e) => (activityQuery.value = (e.target as HTMLInputElement).value)} />
        <Chips label="Result" value={activityResult.value} options={RESULTS} onPick={(v) => (activityResult.value = v)} />
      </div>
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
        {sessionList.value && list.length === 0 && <Empty>{(sessionList.value.sessions.length ? "No run matches these filters." : "No runs yet. Press n to start one.")}</Empty>}
        {!sessionList.value && <Empty>Loading…</Empty>}
      </div>
    </Pane>
  );
}

export function Activity() {
  const tab = activityTab.value;
  const st = sessionList.value?.stats;
  return (
    <>
      <Header title="Activity" scope sub={st ? `${fmtCost(st.today_cost)} today · ${fmtCost(st.month_cost)} this month` : undefined} />
      <Chips label="Activity view" value={tab} options={TABS} onPick={(t) => (activityTab.value = t)} />
      {tab === "sessions" && <><Live /><Sessions /></>}
      {tab === "coordinators" && (
        <Pane label="coordinators">
          {(coordinators.value ?? []).map((c) => (
            <div class="det" key={c.run}>
              <div class="dh"><Tag tone={c.live ? "c-q" : ""}>{c.live ? "live" : "stopped"}</Tag><b>{c.source}</b><span class="dim">{shortRepo(c.repo)} → {c.destination}</span></div>
              <div class="tablewrap"><table class="t"><tbody>{c.queue.map((q) => <tr key={q.issue}><td>#{q.issue}</td><td>{q.title}</td><td>{q.state}</td></tr>)}</tbody></table></div>
              <div class="log">{c.events.map((e, i) => <span key={i}>{e}</span>)}</div>
              <div class="acts">{c.session && <a href={`#/sessions/${c.session}`}>session</a>}<Btn small bad onClick={async () => { if (await askConfirm("Stop refilling this coordinator? Running sessions keep going.")) await mutate(() => http.send("POST", `/api/coordinators/${c.run}/stop`, {}), "Coordinator stopped", ["coordinators"]); }}>Stop refilling</Btn></div>
            </div>
          ))}
          {coordinators.value?.length === 0 && <Empty>No coordinators running. Start one with : and blubird:project-coordinator.</Empty>}
        </Pane>
      )}
      {tab === "grinds" && (
        <Pane label="grinds">
          <div class="tablewrap"><table class="t"><thead><tr><th>PR</th><th>State</th><th>Round</th><th>Reason</th><th /></tr></thead><tbody>
            {(grinds.value ?? []).map((g) => (
              <tr key={`${g.repo}#${g.pr}`}><td class="mono">{g.repo}#{g.pr}</td><td><Tag tone={g.state === "running" ? "c-q" : g.state === "paused" ? "c-w" : "c-o"}>{g.state}</Tag></td><td>{g.rounds}{g.mode ? ` · ${g.mode}` : ""}</td><td>{g.reason ?? ""}</td>
                <td><div class="acts">{g.session && <a href={`#/sessions/${g.session}`}>session</a>}
                  <Btn small onClick={() => mutate(() => http.send("POST", `/api/grinds/${g.repo}/${g.pr}/skip-ci`, {}), "CI wait skipped", ["grinds"])}>Skip CI</Btn>
                  <Btn small bad onClick={async () => { if (await askConfirm(`Stop grinding ${g.repo}#${g.pr}?`)) await mutate(() => http.send("POST", `/api/grinds/${g.repo}/${g.pr}/stop`, {}), "Grind stopped", ["grinds"]); }}>Stop</Btn></div></td></tr>
            ))}</tbody></table></div>
          {grinds.value?.length === 0 && <Empty>No grinds running.</Empty>}
        </Pane>
      )}
      {tab === "panels" && (
        <Pane label="peer review panels">
          {(panels.value ?? []).map((p) => (
            <div class="det" key={p.id}>
              <div class="dh"><Tag tone={p.state === "approved" ? "c-o" : p.state === "running" ? "c-q" : "c-w"}>{p.state}</Tag><b>{p.artifact}</b><span class="dim">round {p.round}/{p.max_rounds} · {p.status.approved}/{p.status.total} approved</span></div>
              <div class="chips">{Object.entries(p.status.lenses).map(([l, v]) => <span class="chip" key={l}>{l}: {v}</span>)}</div>
              <div class="acts">{[1, 2].map((n) => <Btn small key={n} onClick={() => mutate(() => http.send("POST", `/api/review/${p.id}/rounds`, { add: n }), `Added ${n} round(s)`, ["panels"])}>+{n} round{n > 1 ? "s" : ""}</Btn>)}</div>
            </div>
          ))}
          {panels.value?.length === 0 && <Empty>No peer review panels.</Empty>}
        </Pane>
      )}
    </>
  );
}
