/** Dispatches (old aiw): the list (All / Needs you / Live / Finished), the New dispatch form with every
 *  setting and a preview, and the dispatch page (`#/dispatches/<id>`, lane panel with `?lane=`). */
import { useEffect, useRef, useState } from "preact/hooks";
import { http } from "../api/http";
import type { Dispatch, DispatchPlan, DispatchSettings, Effort, Lane, OpenItem } from "../api/types";
import { continueStalled, currentRepo, dispatches, grinds, mutate, repoList, sessionList } from "../state/data";
import { dispatchList } from "../state/select";
import { askConfirm } from "../state/ui";
import { fmtCost, fmtDur, shortRepo } from "../state/format";
import { nav, route, setParam } from "../state/route";
import { Header } from "../components/Header";
import { Popover } from "../components/Shell";
import { AccountPick, EFFORTS, MODELS, openItems } from "../components/Start";
import { Btn, Chips, Empty, Field, Pane, Tag } from "../components/ui";
import { Select } from "../components/Select";
import { cleanTitle, dispatchSeconds, inTab, isLive, isSettled, laneSeconds, needsLanes, parseCost, parseMax, recentDispatches, runSummary, targetError, wantsYou, type Tab } from "../state/dispatchView";
import { sessionTag } from "../components/SessionView";

// ---------- shared ----------
const STAGE: Record<string, [string, string]> = {
  queued: ["Up next", ""], implementing: ["Implementing", "c-q"], grinding: ["Grinding", "c-q"], merge_gate: ["Merge gate", "c-w"], conflict_fix: ["Fixing conflicts", "c-w"],
  awaiting_merge: ["Awaiting merge", "c-w"], followups: ["Follow-ups", "c-q"], closed: ["Done", "c-o"], skipped: ["Skipped", ""],
};
const STATE_TONE: Record<string, string> = { running: "c-q", paused: "c-w", done: "c-o", cancelled: "" };
const live = isLive;
const elapsed = (d: Dispatch) => dispatchSeconds(d, Math.floor(Date.now() / 1000));
const wants = wantsYou;
/** Continue a stalled lane; a 409 (no longer stalled) reloads the dispatches. */
export const continueLane = (d: Pick<Dispatch, "id">, lane: string) =>
  continueStalled(() => http.send("POST", `/api/dispatches/${d.id}/lane`, { lane, action: "continue" }), ["dispatches"]);
const laneCall = (d: Dispatch, lane: string, action: string, text?: string) =>
  mutate(() => http.send("POST", `/api/dispatches/${d.id}/lane`, { lane, action, text }), action === "send" ? "Message sent" : `${action}: ${lane}`, ["dispatches"]);

const settled = isSettled;

function Progress({ d }: { d: Dispatch }) {
  const closed = d.lanes.filter((l) => l.stage === "closed").length;
  const skipped = d.lanes.filter((l) => l.stage === "skipped").length;
  const working = d.lanes.filter((l) => !["queued", "closed", "skipped"].includes(l.stage)).length;
  const rest = Math.max(0, d.lanes.length - closed - skipped - working);
  return (
    <div class="dprog" role="img" aria-label={`${closed} of ${d.lanes.length} issues done${skipped ? `, ${skipped} skipped` : ""}`}>
      <div class="ibar"><i class="b-done" style={{ flexGrow: closed }} /><i class="b-work" style={{ flexGrow: working }} /><i class="b-skip" style={{ flexGrow: skipped }} /><i style={{ flexGrow: rest }} /></div>
      <span class="dim">{closed}/{d.lanes.length}{skipped ? ` · ${skipped} skipped` : ""}</span>
    </div>
  );
}

// ---------- new dispatch ----------
function NewDispatch({ initial = "", onClose }: { initial?: string; onClose: () => void }) {
  const [repo, setRepo] = useState(initial.split("#")[0]?.includes("/") ? initial.split("#")[0]! : currentRepo.value ?? "");
  const [target, setTarget] = useState(initial);
  const [epics, setEpics] = useState<OpenItem[]>([]);
  const [branches, setBranches] = useState<{ branches: string[]; default: string } | null>(null);
  const [st, setSt] = useState<Partial<DispatchSettings>>({ max: 3, grind: "simple", ci: "wait", auto_merge: false, skip_approval: false });
  const [maxText, setMaxText] = useState("3");
  const epicRef = useRef<HTMLInputElement>(null);
  useEffect(() => epicRef.current?.focus(), []);
  const [plan, setPlan] = useState<DispatchPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const small = /,/.test(target);
  const maxNum = parseMax(maxText);
  const costNum = parseCost(st.max_cost == null ? "" : String(st.max_cost));
  const targetErr = targetError(target, small);
  const invalid = !target.trim() || !!targetErr || !maxNum.ok || !costNum.ok;
  useEffect(() => {
    setEpics([]); setBranches(null);
    if (!repo || !repo.includes("/")) return;
    void openItems(repo, "issue").then((items) => setEpics(items.filter((i) => i.labels.some((l) => l.toLowerCase() === "epic")))).catch(() => undefined);
    void http.get<{ branches: string[]; default: string }>(`/api/repos/${repo}/branches`).then(setBranches).catch(() => undefined);
  }, [repo]);
  const body = () => {
    const v = /^#?\d+$/.test(target.trim()) && repo ? `${repo}#${target.trim().replace("#", "")}` : target.trim();
    const settings = Object.fromEntries(Object.entries(st).filter(([, x]) => x !== "" && x !== undefined && x !== null));
    if (small) settings.feature_branch = null;
    return /^[\w./-]+#\d+(\s*,\s*[\w./-]+#\d+)+$/.test(v) ? { issues: v.split(/\s*,\s*/), settings } : { epic: v, settings };
  };
  const set = <K extends keyof DispatchSettings>(k: K, v: DispatchSettings[K] | undefined) => { setSt({ ...st, [k]: v }); setPlan(null); };
  const setMax = (text: string) => { setMaxText(text); const n = parseMax(text); set("max", n.ok ? n.value ?? undefined : undefined); };
  const preview = async () => setPlan((await mutate(() => http.send<DispatchPlan>("POST", "/api/dispatches/plan", body()), null)) ?? null);
  const startIt = async () => {
    setBusy(true);
    const d = await mutate(() => http.send<Dispatch>("POST", "/api/dispatches", body()), "Dispatch started", ["dispatches"]);
    setBusy(false);
    if (d) { onClose(); nav(`#/dispatches/${d.id}`); }
  };
  return (
    <Pane label={small ? "run small changes" : "run an epic"}>
      <form class="form" onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); onClose(); } }} onSubmit={async (e) => { e.preventDefault(); if (!invalid) await preview(); }}>
        <div class="fields">
          {!small && <Field label="Repository"><Select label="Repository" value={repo} onChange={(v) => { setRepo(v); setTarget(""); }} options={repoList.value.filter((r) => !r.slug.startsWith("local/")).map((r) => ({ value: r.slug, label: r.slug.split("/")[1] ?? r.slug, hint: r.slug.split("/")[0] }))} /></Field>}
          <Field label={small ? "Issues" : "Epic"} hint={small ? "comma-separated, 1–30" : "pick one, or type owner/name#N, #N or a link"} error={targetErr}>
            <input ref={epicRef} list="dispatch-epics" aria-invalid={!!targetErr} value={target} onInput={(e) => { setTarget((e.target as HTMLInputElement).value); setPlan(null); }} placeholder={`${repo || "owner/name"}#123`} />
            <datalist id="dispatch-epics">{epics.map((e) => <option key={e.number} value={`${repo}#${e.number}`}>{e.title}</option>)}</datalist>
          </Field>
        </div>
        <div class="fields">
          <Field label="Grind"><Select label="Grind" value={st.grind ?? "simple"} onChange={(v) => set("grind", v as DispatchSettings["grind"])} options={[["off", "Off"], ["simple", "Simple"], ["full", "Full"]]} /></Field>
          <Field label="CI"><Select label="CI" value={st.ci ?? "wait"} onChange={(v) => set("ci", v as DispatchSettings["ci"])} options={[["wait", "Wait"], ["defer", "Defer"], ["ignore", "Ignore"]]} /></Field>
          <Field label="At most at once" hint="1–10, empty for the default" error={maxNum.ok ? "" : maxNum.error}><input type="number" min={1} max={10} step={1} aria-invalid={!maxNum.ok} value={maxText} onInput={(e) => setMax((e.target as HTMLInputElement).value)} /></Field>
          <Field label="Cost cap (USD)" error={costNum.ok ? "" : costNum.error}><input type="number" min={0} step={1} placeholder="none" aria-invalid={!costNum.ok} value={st.max_cost ?? ""} onInput={(e) => { const v = (e.target as HTMLInputElement).value; set("max_cost", v === "" ? null : Number(v)); }} /></Field>
        </div>
        <div class="fields">
          <label class="fld check"><span><input type="checkbox" checked={!!st.auto_merge} onChange={(e) => set("auto_merge", (e.target as HTMLInputElement).checked)} /> Auto-merge</span></label>
          <label class="fld check"><span><input type="checkbox" checked={!!st.skip_approval} onChange={(e) => set("skip_approval", (e.target as HTMLInputElement).checked)} /> Skip approval</span></label>
          <Field label="Base branch"><Select label="Base branch" value={st.base_branch ?? ""} onChange={(v) => set("base_branch", v || null)} options={[["", branches ? `default (${branches.default})` : "default"], ...(branches?.branches ?? []).map((b) => [b, b] as [string, string])]} /></Field>
          {!small && <Field label="Feature branch" hint="optional: lanes merge here, then one PR to base"><input value={st.feature_branch ?? ""} placeholder="none" onInput={(e) => set("feature_branch", (e.target as HTMLInputElement).value || null)} /></Field>}
        </div>
        <div class="fields">
          <Field label="Model"><Select label="Model" value={st.model ?? ""} onChange={(v) => set("model", v || null)} options={[["", "default"], ...MODELS.map((m) => [m, m] as [string, string])]} /></Field>
          <Field label="Effort"><Select label="Effort" value={st.effort ?? ""} onChange={(v) => set("effort", (v || null) as Effort | null)} options={[["", "default"], ...EFFORTS.map((m) => [m, m] as [string, string])]} /></Field>
        </div>
        <AccountPick value={st.account ?? ""} onChange={(v) => set("account", v || null)} />
        <div class="acts">
          <Btn type="submit" disabled={invalid}>Preview</Btn>
          <Btn primary disabled={invalid || busy} onClick={startIt}>{plan ? `Start ${plan.lanes.length} issues` : "Start"}</Btn>
          <Btn onClick={onClose}>Cancel</Btn>
        </div>
        {plan && (
          <div class="plan">
            <b>{plan.title}</b>
            {plan.warnings.map((w) => <div class="banner" key={w}>{w}</div>)}
            {plan.waves.map((w, i) => <div key={i}><span class="dim">{i === 0 ? "Starts first" : `Then (${i + 1})`}:</span> {w.map((k) => { const l = plan.lanes.find((x) => x.key === k); return <span key={k} class="chip">{shortRepo(k.split("#")[0])}#{k.split("#")[1]} {l?.title}{l && !l.refined ? " · unrefined" : ""}</span>; })}</div>)}
          </div>
        )}
      </form>
    </Pane>
  );
}

// ---------- list ----------
const TABS: [Tab, string][] = [["all", "All"], ["needs", "Needs you"], ["live", "Live"], ["done", "Finished"]];
export { inTab };

export function Dispatches() {
  return route.value.id ? <DispatchPage /> : <DispatchList />;
}

function DispatchList() {
  const [tab, setTab] = useState<Tab>("all");
  const preset = route.value.query.new ?? "";
  const [showNew, setShowNew] = useState(!!preset);
  const open = showNew || !!preset;
  const wasOpen = useRef(false);
  const trigger = useRef<HTMLSpanElement>(null);
  const [older, setOlder] = useState(false);
  const close = () => { setShowNew(false); if (preset) setParam("new", "", true); };
  // Escape or Cancel hands focus back to the "Run an epic" button, which only exists while the form is shut.
  useEffect(() => { if (wasOpen.current && !open) trigger.current?.querySelector("button")?.focus(); wasOpen.current = open; }, [open]);
  const tabbed = dispatchList.value.filter((d) => inTab(d, tab));
  const recent = tab === "all" && !older ? recentDispatches(tabbed, Math.floor(Date.now() / 1000)) : tabbed;
  const list = recent;
  const hidden = tabbed.length - recent.length;
  return (
    <>
      <Header title="Dispatches" scope sub={runSummary(dispatchList.value)}>
        <span ref={trigger}>{!open && <Btn primary onClick={() => setShowNew(true)}>Run an epic</Btn>}</span>
      </Header>
      {open && <NewDispatch key={preset} initial={preset} onClose={close} />}
      <Chips label="Dispatch filter" value={tab} options={TABS} onPick={setTab} />
      {list.length > 0 && (
        <div class="tablewrap"><table class="t dlist"><thead><tr><th>State</th><th>Title</th><th>Issues</th><th>Time</th><th>Spend</th></tr></thead><tbody>
          {list.map((d) => {
            const needs = needsLanes(d).length;
            return (
              <tr key={d.id} class="click" onClick={() => nav(`#/dispatches/${d.id}`)}>
                <td><Tag tone={needs ? "c-w" : STATE_TONE[d.state]}>{needs ? `${needs} need you` : d.state}</Tag></td>
                <td><a href={`#/dispatches/${d.id}`}>{cleanTitle(d.title)}</a><div class="dim mono">{d.epic ?? `${d.lanes.length} issues`}</div></td>
                <td><Progress d={d} /></td><td class="mono">{fmtDur(elapsed(d))}</td><td class="mono">{fmtCost(d.totals.cost)}</td>
              </tr>
            );
          })}
        </tbody></table></div>
      )}
      {hidden > 0 && <div class="acts"><Btn small onClick={() => setOlder(true)}>Show older ({hidden})</Btn></div>}
      {dispatches.value && list.length === 0 && <Empty>{dispatchList.value.length ? "No dispatch in this view." : "No dispatches yet. Run an epic, or pick small changes to run."}</Empty>}
      {!dispatches.value && <Empty>Loading…</Empty>}
    </>
  );
}

// ---------- the dispatch page ----------
function PauseButton({ d }: { d: Dispatch }) {
  const [open, setOpen] = useState(false);
  const pause = async (now: boolean) => {
    setOpen(false);
    if (now && !(await askConfirm(`Pause ${cleanTitle(d.title)} now? Running sessions stop.`))) return;
    await mutate(() => http.send("POST", `/api/dispatches/${d.id}/state`, { state: "paused", now }), now ? "Paused now" : "Pausing after the running issues", ["dispatches"]);
  };
  return (
    <Popover open={open} setOpen={setOpen} trigger={<Btn onClick={() => setOpen(!open)}>Pause ▾</Btn>}>
      <div class="menu">
        <button type="button" class="pi" onClick={() => pause(false)}>After the running issues<span class="r">no new starts</span></button>
        <button type="button" class="pi" onClick={() => pause(true)}>Now<span class="r">stops running sessions</span></button>
      </div>
    </Popover>
  );
}

/** A number setting: validated as you type, saved on blur or Enter, with an inline "Saved". */
function NumSetting({ label, value, placeholder, parse, onSave }: { label: string; value: number | null; placeholder?: string; parse: typeof parseMax; onSave: (v: number | null) => Promise<unknown> }) {
  const [text, setText] = useState(value == null ? "" : String(value));
  const [saved, setSaved] = useState(false);
  useEffect(() => setText(value == null ? "" : String(value)), [value]);
  const n = parse(text);
  const commit = async () => {
    if (!n.ok || n.value === value) return;
    if ((await onSave(n.value)) !== undefined) { setSaved(true); setTimeout(() => setSaved(false), 2000); }
  };
  return (
    <Field label={label} error={n.ok ? "" : n.error} hint={saved ? "Saved" : undefined}>
      <input type="number" min={0} placeholder={placeholder} aria-invalid={!n.ok} value={text}
        onInput={(e) => { setText((e.target as HTMLInputElement).value); setSaved(false); }} onBlur={() => void commit()}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void commit(); } }} />
    </Field>
  );
}

function Settings({ d }: { d: Dispatch }) {
  const set = (patch: Partial<DispatchSettings>) => mutate(() => http.send("POST", `/api/dispatches/${d.id}/settings`, patch), "Saved", ["dispatches"]);
  const s = d.settings;
  return (
    <div class="fields">
      <NumSetting label="At most at once" value={s.max} parse={parseMax} onSave={(v) => set({ max: v ?? undefined })} />
      <Field label="Grind"><Select label="Grind" value={s.grind} onChange={(v) => void set({ grind: v as DispatchSettings["grind"] })} options={[["off", "Off"], ["simple", "Simple"], ["full", "Full"]]} /></Field>
      <Field label="CI"><Select label="CI" value={s.ci} onChange={(v) => void set({ ci: v as DispatchSettings["ci"] })} options={[["wait", "Wait"], ["defer", "Defer"], ["ignore", "Ignore"]]} /></Field>
      <NumSetting label="Cost cap (USD)" value={s.max_cost} placeholder="none" parse={parseCost} onSave={(v) => set({ max_cost: v })} />
      <label class="fld check"><span><input type="checkbox" checked={s.auto_merge} onChange={(e) => void set({ auto_merge: (e.target as HTMLInputElement).checked })} /> Auto-merge</span></label>
      <label class="fld check"><span><input type="checkbox" checked={s.skip_approval} onChange={(e) => void set({ skip_approval: (e.target as HTMLInputElement).checked })} /> Skip approval</span></label>
    </div>
  );
}

function LaneLine({ d, l }: { d: Dispatch; l: Lane }) {
  const [label0, tone0] = STAGE[l.stage] ?? [l.stage, ""];
  const ended = !live(d) && !settled(l);
  const [label, tone] = ended ? ["Cancelled", ""] : l.stranded ? ["Can't start", "c-b"] : [label0, tone0];
  const openDeps = l.deps.filter((k) => { const y = d.lanes.find((x) => x.key === k); return !y || !settled(y); });
  const why = ended ? "" : l.stranded ?? l.needs_you ?? l.stalled ?? l.held ?? l.gate ?? l.skip_reason ?? (openDeps.length && l.stage === "queued" ? `after ${openDeps.map((k) => `#${k.split("#")[1]}`).join(", ")}` : "");
  const secs = laneSeconds(d, l);
  return (
    <button type="button" class={`irow lane${route.value.query.lane === l.key ? " sel" : ""}`} onClick={() => setParam("lane", l.key, true)}>
      <span />
      <Tag tone={wants(l) && !ended ? "c-w" : tone}>{ended ? label : l.needs_you ? "Needs you" : l.stalled ? "Stalled" : label}{l.paused && !ended ? " · paused" : ""}</Tag>
      <span class="t"><span class="mono">{shortRepo(l.repo)}#{l.n}</span> {l.title}{why && <span class="dim"> · {why}</span>}{l.pr ? <span class="dim"> · PR #{l.pr}</span> : null}</span>
      <span class="dim mono">{secs ? fmtDur(secs) : ""} {l.usage.cost ? fmtCost(l.usage.cost) : ""}</span>
    </button>
  );
}

const PR_URL = /https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/pull\/\d+/g;

/** Sessions for the lane's issue, and the PRs the newest one mentions (it may open PRs in other repos). */
function IssueWork({ l }: { l: Lane }) {
  const runs = (sessionList.value?.sessions ?? []).filter((s) => s.link && `${s.link.owner}/${s.link.repo}`.toLowerCase() === l.repo.toLowerCase() && s.link.issue === l.n);
  const last = runs.find((s) => !["running", "starting", "waiting"].includes(s.status));
  const [prs, setPrs] = useState<string[]>([]);
  useEffect(() => {
    setPrs([]);
    if (!last) return;
    void http.get<{ events: { kind: string; text?: string | null }[] }>(`/api/sessions/${last.id}/stream?offset=0`).then((t) => {
      const text = t.events.filter((e) => e.kind === "text" || e.kind === "result").slice(-6).map((e) => e.text ?? "").join("\n");
      const own = l.pr ? `https://github.com/${l.repo}/pull/${l.pr}` : "";
      setPrs([...new Set(text.match(PR_URL) ?? [])].filter((u) => u.toLowerCase() !== own.toLowerCase()));
    }, () => undefined);
  }, [last?.id]);
  if (!runs.length) return null;
  return (
    <div class="form">
      {prs.length > 0 && (
        <div><div class="gh">PRs it opened elsewhere</div>
          <span class="dim">The dispatch merges only this lane's own PR. Review and merge these yourself.</span>
          {prs.map((u) => { const m = /github\.com\/([^/]+\/[^/]+)\/pull\/(\d+)/.exec(u)!; return <div key={u}><a href={u}>{m[1]}#{m[2]}</a></div>; })}
        </div>
      )}
      <div><div class="gh">Sessions for #{l.n}</div>
        {runs.slice(0, 5).map((s) => <a key={s.id} class="row" href={`#/sessions/${s.id}`}><span class={`tag ${sessionTag(s)[1]}`}>{sessionTag(s)[0]}</span><span class="t">{s.skill ?? "free text"}</span><span class="w">{fmtDur(s.duration_s)}</span></a>)}
      </div>
    </div>
  );
}

function LanePanel({ d, l }: { d: Dispatch; l: Lane }) {
  const [msg, setMsg] = useState("");
  const [menu, setMenu] = useState(false);
  const open = live(d);
  const g = (grinds.value ?? []).find((x) => x.pr === l.pr && x.repo.toLowerCase() === l.repo.toLowerCase());
  const act = async (a: string) => {
    setMenu(false);
    const ask = a === "merge" ? `Merge the PR for ${l.key} now?` : a === "skip" ? `Skip ${l.key}? It will not be worked on in this dispatch, and issues that depend on it cannot start until you retry it or unblock them.` : "";
    if (ask && !(await askConfirm(ask))) return;
    await laneCall(d, l.key, a);
  };
  const active = open && !settled(l) && l.stage !== "queued";
  const mergeable = open && !!l.pr && (l.stage === "awaiting_merge" || l.stage === "merge_gate");
  const dependents = d.lanes.filter((x) => x.skipped_deps?.includes(l.key));
  return (
    <Pane label={`lane · ${shortRepo(l.repo)}#${l.n}`}>
      <div class="form">
        <div class="dh"><b>{l.title}</b><span class="grow" /><Btn small onClick={() => setParam("lane", "", true)}>Close</Btn></div>
        <div class="dim">{!open && !settled(l) ? "Cancelled" : l.stranded ? "Can't start" : (STAGE[l.stage] ?? [l.stage])[0]}{l.skip_reason ? ` · ${l.skip_reason}` : ""}{l.paused ? " · paused" : ""}{l.hold_merge ? " · merge held" : ""}{g ? ` · grind ${g.state}, round ${g.rounds}` : ""}{l.gate && !settled(l) ? ` · ${l.gate}` : ""}</div>
        {open && l.needs_you && <div class="banner">{l.needs_you}</div>}
        {open && l.stalled && <div class="banner">Stalled: {l.stalled}</div>}
        {open && l.stranded && (
          <div class="banner">This issue waits on {(l.skipped_deps ?? []).map((k) => `#${k.split("#")[1]}`).join(", ") || "a blocker"}, which {l.skipped_deps?.length === 1 ? "was" : "were"} skipped, so it can never start as things stand.
            {(l.skipped_deps ?? []).length > 0 && <Btn small primary onClick={() => act("unblock")}>Unblock: start without {l.skipped_deps!.length === 1 ? "it" : "them"}</Btn>}</div>
        )}
        {l.stage === "skipped" && (
          <div class="banner">Skipped{l.skip_reason ? ` (${l.skip_reason})` : ""}. Nothing more happens on it in this dispatch.
            {dependents.length > 0 && ` ${dependents.length} issue${dependents.length === 1 ? " waits" : "s wait"} on it.`}
            <Btn small onClick={() => act("retry")}>Run it again</Btn></div>
        )}
        {l.unblocked && l.unblocked.length > 0 && <span class="dim">Started without skipped {l.unblocked.map((k) => `#${k.split("#")[1]}`).join(", ")}.</span>}
        <div class="acts">
          {l.session && <a class="btn sm" href={`#/sessions/${l.session}`}>Open session</a>}
          <a class="btn sm" href={`https://github.com/${l.repo}/issues/${l.n}`}>Issue</a>
          {l.pr && <a class="btn sm" href={`https://github.com/${l.repo}/pull/${l.pr}`}>PR #{l.pr}</a>}
          {mergeable && <Btn small primary onClick={() => act("merge")}>Merge PR</Btn>}
          {open && l.stalled && <Btn small primary onClick={() => continueLane(d, l.key)}>Continue</Btn>}
          {open && wants(l) && <Btn small onClick={() => act("retry")}>Retry</Btn>}
          {open && l.paused && !settled(l) && <Btn small onClick={() => act("resume")}>Resume</Btn>}
          {open && !settled(l) && (
            <Popover open={menu} setOpen={setMenu} trigger={<Btn small onClick={() => setMenu(!menu)}>More ▾</Btn>}>
              <div class="menu">
                {!l.paused && <button type="button" class="pi" onClick={() => act("pause")}>Pause this issue</button>}
                {l.pr && <button type="button" class="pi" onClick={() => act("merge")}>Merge now</button>}
                {l.pr && <button type="button" class="pi" onClick={() => act(l.hold_merge ? "unhold" : "hold")}>{l.hold_merge ? "Let it merge" : "Hold the merge"}</button>}
                {active && <button type="button" class="pi" onClick={() => act("retry")}>Retry in a new session</button>}
                <button type="button" class="pi bad" onClick={() => act("skip")}>Skip</button>
              </div>
            </Popover>
          )}
        </div>
        {l.session && active && live(d) && (
          <form class="acts" onSubmit={async (e) => { e.preventDefault(); if (msg.trim() && (await laneCall(d, l.key, "send", msg.trim())) !== undefined) setMsg(""); }}>
            <input class="grow" placeholder="Message the session (it reads it at its next turn)" aria-label="Message the lane's session" value={msg} onInput={(e) => setMsg((e.target as HTMLInputElement).value)} />
            <Btn small type="submit" disabled={!msg.trim()}>Send</Btn>
          </form>
        )}
        <IssueWork l={l} />
      </div>
    </Pane>
  );
}

const day = (at: number) => new Date(at * 1000).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
const clock24 = (at: number) => new Date(at * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
/** The newest 40 events, newest first, with a date separator wherever the day changes. */
function eventRows(events: NonNullable<Dispatch["events"]>) {
  const rows: preact.ComponentChildren[] = [];
  let last = "";
  for (const [i, e] of events.slice(-40).reverse().entries()) {
    const dd = day(e.at);
    if (dd !== last) { rows.push(<span key={`d${dd}`} class="daysep dim">{dd}</span>); last = dd; }
    rows.push(<span key={i}><span class="dim mono">{clock24(e.at)}</span> {e.lane ? <b>#{e.lane.split("#")[1]} </b> : null}{e.text}</span>);
  }
  return rows;
}

function DispatchPage() {
  const id = route.value.id!;
  const [full, setFull] = useState<Dispatch | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const fromList = (dispatches.value ?? []).find((d) => d.id === id);
  // Refetch the full record when the id changes or the list row changes in a way the page shows, not on every list reload.
  const sig = fromList ? `${fromList.state}|${fromList.ended_at}|${fromList.totals.closed}|${fromList.lanes.map((l) => `${l.stage}${l.pr}${l.needs_you}${l.stalled}${l.paused}${l.hold_merge}${l.stranded}`).join(",")}` : "";
  useEffect(() => { setFull(null); }, [id]);
  useEffect(() => { void http.get<Dispatch>(`/api/dispatches/${id}`).then(setFull, () => setFull(null)); }, [id, sig]);
  const d = (full?.id === id ? full : null) ?? fromList;
  if (!d) return <><Header title="Dispatch"><Btn small onClick={() => nav("#/dispatches")}>← Dispatches</Btn></Header><Empty>{dispatches.value ? "No such dispatch." : "Loading…"}</Empty></>;
  const lane = d.lanes.find((l) => l.key === route.value.query.lane);
  const open = live(d);
  // An ended dispatch asks for nothing: its open lanes are settled as Cancelled.
  const cancelled = open ? [] : d.lanes.filter((l) => !settled(l));
  const needs = needsLanes(d);
  const stranded = open ? d.lanes.filter((l) => !wants(l) && l.stranded && l.stage === "queued") : [];
  const building = open ? d.lanes.filter((l) => !wants(l) && !["queued", "closed", "skipped"].includes(l.stage)) : [];
  const next = open ? d.lanes.filter((l) => !wants(l) && !l.stranded && l.stage === "queued") : [];
  const done = d.lanes.filter((l) => l.stage === "closed");
  const skipped = d.lanes.filter((l) => l.stage === "skipped");
  const blockers = [...new Set(stranded.flatMap((l) => l.skipped_deps ?? []))];
  const unblockAll = async () => {
    const ls = stranded.filter((l) => (l.skipped_deps ?? []).length);
    if (!(await askConfirm(`Let ${ls.length} issue${ls.length === 1 ? "" : "s"} start without ${blockers.map((k) => `#${k.split("#")[1]}`).join(", ")}? They lose that dependency in this dispatch.`))) return;
    for (const l of ls) await laneCall(d, l.key, "unblock");
  };
  const allDone = d.lanes.length > 0 && d.lanes.every(settled);
  const anyFailed = d.lanes.some((l) => (l.stage === "skipped" && !!l.skip_reason?.startsWith("start failed")) || !!l.needs_you || !!l.held);
  const setState = (state: string) => mutate(() => http.send("POST", `/api/dispatches/${d.id}/state`, { state }), state === "running" ? "Resumed" : "Cancelled", ["dispatches"]);
  const end = (a: string, t: string) => mutate(() => http.send("POST", `/api/dispatches/${d.id}/end`, { action: a }), `${t}: started`, ["dispatches"]);
  const section = (name: string, ls: Lane[]) => (ls.length ? <div role="group" aria-label={name}><div class="gh">{name} · {ls.length}</div>{ls.map((l) => <LaneLine key={l.key} d={d} l={l} />)}</div> : null);
  return (
    <>
      <nav class="crumbs" aria-label="Breadcrumb"><a href="#/dispatches">Dispatches</a> › <span>{cleanTitle(d.title)}</span></nav>
      <Header title={cleanTitle(d.title)} sub={<><Tag tone={STATE_TONE[d.state]}>{d.state}</Tag> {d.epic && <a href={`https://github.com/${d.epic.split("#")[0]}/issues/${d.epic.split("#")[1]}`} class="mono">{d.epic}</a>} · {fmtDur(elapsed(d))} · {fmtCost(d.totals.cost)}</>}>
        <Btn onClick={() => setShowSettings(!showSettings)}>Settings</Btn>
        {d.state === "running" && <PauseButton d={d} />}
        {d.state === "paused" && <Btn primary onClick={() => setState("running")}>Resume</Btn>}
        {live(d) && <Btn bad onClick={async () => { if (await askConfirm(`Cancel ${d.title}? Running sessions stop and no new issue starts.`)) await setState("cancelled"); }}>Cancel</Btn>}
      </Header>
      {showSettings && <Pane label="settings">{live(d) ? <Settings d={d} /> : <span class="dim">This dispatch has ended.</span>}</Pane>}
      <Progress d={d} />
      {stranded.length > 0 && live(d) && (
        <div class="banner bad" role="alert">
          {stranded.length} issue{stranded.length === 1 ? " can't" : "s can't"} start{blockers.length ? `: ${stranded.length === 1 ? "it waits" : "they wait"} on skipped ${blockers.map((k) => `#${k.split("#")[1]}`).join(", ")}` : " (a dependency cycle)"}. The dispatch will stop there.
          {blockers.map((k) => <Btn key={k} small onClick={() => laneCall(d, k, "retry")}>Run #{k.split("#")[1]} again</Btn>)}
          {blockers.length > 0 && <Btn small primary onClick={unblockAll}>Unblock them</Btn>}
        </div>
      )}
      {allDone && (
        <Pane label="all issues are done: what next?">
          <div class="acts">
            {d.settings.feature_branch && <Btn primary onClick={() => end("open-pr", "Open PR")}>Open the PR from {d.settings.feature_branch}</Btn>}
            <Btn onClick={() => end("qa", "QA")}>Run QA</Btn>
            {d.settings.feature_branch && <Btn onClick={() => end("grind-pr", "Grind")}>Grind the final PR</Btn>}
            {anyFailed && <Btn small onClick={() => mutate(() => http.send("POST", `/api/dispatches/${d.id}/retry-failed`, {}), "Retrying failed lanes", ["dispatches"])}>Retry failed</Btn>}
          </div>
        </Pane>
      )}
      <div class="dpage">
        <Pane label="issues">
          {section("Needs you", needs)}{section("Can't start", stranded)}{section("Building now", building)}{section("Up next", next)}{section(d.state === "cancelled" ? "Cancelled" : "Not finished", cancelled)}{section("Done", done)}{section("Skipped", skipped)}
          {!d.lanes.length && <Empty>No issues in this dispatch yet.</Empty>}
        </Pane>
        <div class="dside">
          {lane && <LanePanel key={lane.key} d={d} l={lane} />}
          <Pane label="activity">
            <div class="log">{eventRows(d.events ?? [])}</div>
            {!d.events?.length && <span class="dim">No events yet.</span>}
          </Pane>
        </div>
      </div>
    </>
  );
}
