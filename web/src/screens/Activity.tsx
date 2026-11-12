import { useEffect, useRef, useState } from "preact/hooks";
import { http } from "../api/http";
import type { CleanupItem } from "../api/types";
import { useFocusTrap } from "../components/ui";
import { activityTab, coordinators, grinds, inScope, mutate, panels, sessionList, type ActivityTab } from "../state/data";
import { activityQuery, activityResult, RUNNING, runList } from "../state/select";
import { askConfirm, detailOpen, sel, setSel } from "../state/ui";
import { prefs } from "../state/prefs";
import { ago, fmtCost, fmtDur, shortRepo } from "../state/format";
import { Header } from "../components/Header";
import { statusTone } from "../components/SessionView";
import { Btn, Chips, Empty, Pane, Tag } from "../components/ui";

/** Clean up old (old aiw): finished sessions to remove; ones with unsaved work start unticked. */
function CleanupDialog({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<CleanupItem[] | null>(null);
  const [keep, setKeep] = useState<Set<string>>(new Set());
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);
  useEffect(() => { void http.get<{ items: CleanupItem[] }>("/api/sessions/cleanup").then((r) => { setItems(r.items); setKeep(new Set(r.items.filter((i) => i.flags.length).map((i) => i.key))); }, () => setItems([])); }, []);
  const chosen = (items ?? []).filter((i) => !keep.has(i.key));
  const toggle = (k: string) => { const s = new Set(keep); if (s.has(k)) s.delete(k); else s.add(k); setKeep(s); };
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div class="dlg" ref={box} role="dialog" aria-modal="true" aria-labelledby="clean-h"><div class="form">
        <h2 id="clean-h" class="dlg-h">Clean up old sessions</h2>
        <span class="dim">Removes the session records and logs from setu. Checkouts and branches are not touched. Ones with unsaved work start unticked.</span>
        {!items && <span class="dim">Loading…</span>}
        {items && !items.length && <span class="dim">Nothing to clean up.</span>}
        <div class="picker-list tall">{(items ?? []).map((i) => (
          <label key={i.key} class="opt inline"><input type="checkbox" checked={!keep.has(i.key)} onChange={() => toggle(i.key)} />
            <span><b>{i.label}</b> <span class="dim">{shortRepo(i.repo)}</span>{i.flags.map((f) => <span key={f} class="tag c-w"> {f}</span>)}</span></label>
        ))}</div>
        <div class="acts">
          <Btn primary bad disabled={!chosen.length} onClick={async () => {
            if (await mutate(() => http.send("POST", "/api/sessions/cleanup", { keys: chosen.map((i) => i.key) }), `Removed ${chosen.length} sessions`, ["sessions"])) onClose();
          }}>Remove {chosen.length} sessions</Btn>
          <Btn onClick={onClose}>Cancel</Btn>
        </div>
      </div></div>
    </div>
  );
}

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
  const [clean, setClean] = useState(false);
  const st = sessionList.value?.stats;
  return (
    <>
      <Header title="Activity" scope sub={st ? `${fmtCost(st.today_cost)} today · ${fmtCost(st.month_cost)} this month` : undefined}>
        <Btn onClick={() => setClean(true)}>Clean up old</Btn>
      </Header>
      {clean && <CleanupDialog onClose={() => setClean(false)} />}
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
