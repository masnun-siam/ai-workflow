/** The old aiw feature page: strip, build map, and the Issues, PRD, Peer review and Sessions tabs. */
import { useEffect, useState } from "preact/hooks";
import { http } from "../api/http";
import type { Feature, FeatureIssue, FeatureIssueState, PRDFile, ReviewOffers, Session } from "../api/types";
import { describeError } from "../state/actions";
import { features, load, loadMany, mutate, panels, products } from "../state/data";
import { exec } from "../state/exec";
import { ago, fmtCost } from "../state/format";
import { nav, route, setParam } from "../state/route";
import { askConfirm, toast } from "../state/ui";
import { Header } from "../components/Header";
import { Markdown } from "../components/Markdown";
import { statusTone } from "../components/SessionView";
import { Btn, Empty, Pane, Tag } from "../components/ui";
import { FeatureStrip } from "./Features";

type Tab = "issues" | "prd" | "review" | "sessions";
const TABS: [Tab, string][] = [["issues", "Issues"], ["prd", "PRD"], ["review", "Peer review"], ["sessions", "Sessions"]];
const defaultTab = (f: Feature): Tab => (f.stage === "draft" ? "prd" : f.stage === "review" ? "review" : "issues");

const STATE: Record<FeatureIssueState, [string, string]> = {
  waiting: ["Needs you", "c-w"], failed: ["Failed", "c-b"], conflict: ["Conflict", "c-b"], ci_failed: ["CI failed", "c-b"], mergeable: ["Ready to merge", "c-o"],
  in_review: ["In review", "c-q"], in_progress: ["Running", "c-q"], dispatch: ["In dispatch", "c-q"], ready: ["Ready", "c-o"], blocked: ["Blocked", ""], unrefined: ["Needs refining", "c-w"],
};
const BUCKETS: [string, FeatureIssueState[]][] = [
  ["Needs you", ["waiting", "failed", "conflict", "ci_failed", "mergeable"]], ["In flight", ["in_progress", "dispatch", "in_review"]],
  ["Ready", ["ready"]], ["Blocked", ["blocked"]], ["Needs refining", ["unrefined"]],
];

async function startRun(body: Record<string, unknown>, label: string): Promise<Session | undefined> {
  return mutate(() => http.send<Session>("POST", "/api/sessions", { ...body, guard: true }), `Started ${label}`, ["features", "sessions"]);
}

function BuildMap({ f }: { f: Feature }) {
  if (!f.issues.length && !f.done.length) return null;
  return (
    <div class="bmap" aria-label="Build map">
      {f.done.map((d) => <a key={d.key} class="tile t-done" href={d.url} target="_blank" rel="noreferrer" title={`#${d.n} ${d.title}: done`}>#{d.n}</a>)}
      {f.issues.map((i) => <a key={i.key} class={`tile t-${i.state}`} href={`#issue-${i.n}`} onClick={(e) => { e.preventDefault(); setParam("tab", "issues", true); setTimeout(() => document.getElementById(`issue-${i.n}`)?.scrollIntoView({ block: "center" }), 0); }} title={`#${i.n} ${i.title}: ${STATE[i.state][0]}`}>#{i.n}</a>)}
      {f.dispatch && <span class="dim">Dispatch {f.dispatch.state}: {f.dispatch.closed}/{f.dispatch.lanes} lanes closed{f.dispatch.needs ? `, ${f.dispatch.needs} need you` : ""}. <a href="#/dispatches">Open dispatch</a></span>}
    </div>
  );
}

function IssueRow({ i, picked, onPick }: { i: FeatureIssue; picked: boolean; onPick?: (v: boolean) => void }) {
  const [label, tone] = STATE[i.state];
  return (
    <div class="irow" id={`issue-${i.n}`}>
      {onPick ? <input type="checkbox" aria-label={`Pick #${i.n}`} checked={picked} onChange={(e) => onPick((e.target as HTMLInputElement).checked)} /> : <span />}
      <Tag tone={tone}>{label}</Tag>
      <span class="t"><a href={i.url} target="_blank" rel="noreferrer" class="mono">#{i.n}</a> {i.title}
        {i.bug && <span class="tag c-b"> bug</span>}{i.priority && <span class="dim"> · {i.priority}</span>}
        {i.state === "blocked" && <span class="dim"> · after {i.blockers.join(", ")}</span>}
        {i.pr && <> · <a href={i.pr.url} target="_blank" rel="noreferrer">PR #{i.pr.n}</a> <span class="dim">CI {i.pr.ci}{i.pr.review !== "none" ? `, ${i.pr.review.replace("_", " ")}` : ""}</span></>}
      </span>
      <div class="acts">
        {i.session && <a href={`#/sessions/${i.session}`}>session</a>}
        {i.actions.map((a) => <Btn key={a.label} small primary={a.primary} onClick={() => exec(a)}>{a.label}</Btn>)}
      </div>
    </div>
  );
}

function IssuesTab({ f }: { f: Feature }) {
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [task, setTask] = useState("");
  const unrefined = f.issues.filter((i) => i.state === "unrefined");
  const pick = (n: number, v: boolean) => { const s = new Set(picked); if (v) s.add(n); else s.delete(n); setPicked(s); };
  if (!f.epic) return <Empty>No epic yet. {f.stage === "approved" ? "Create the tasks to file the epic and its issues." : "Approve the PRD first: approving files the epic."}</Empty>;
  return (
    <>
      {unrefined.length > 0 && (
        <div class="acts">
          <Btn small primary disabled={!picked.size} onClick={async () => {
            const nums = [...picked].sort((a, b) => a - b);
            if (await startRun({ step: "refine-issues", repo: f.epic!.repo, args: nums.join(" ") }, `refine-issues ${nums.map((n) => `#${n}`).join(" ")}`)) setPicked(new Set());
          }}>Refine {picked.size || ""} picked</Btn>
          <Btn small onClick={() => setPicked(new Set(unrefined.map((i) => i.n)))}>Pick all {unrefined.length}</Btn>
          {picked.size > 0 && <Btn small onClick={() => setPicked(new Set())}>Clear</Btn>}
        </div>
      )}
      {BUCKETS.map(([name, states]) => {
        const rows = f.issues.filter((i) => states.includes(i.state));
        if (!rows.length) return null;
        return (
          <div key={name} role="group" aria-label={name}>
            <div class="gh">{name} · {rows.length}</div>
            {rows.map((i) => <IssueRow key={i.key} i={i} picked={picked.has(i.n)} onPick={i.state === "unrefined" ? (v) => pick(i.n, v) : undefined} />)}
          </div>
        );
      })}
      {f.done.length > 0 && (
        <details><summary class="gh">Done · {f.done.length}</summary>
          {f.done.map((d) => <div key={d.key} class="irow"><span /><Tag tone="c-o">Done</Tag><span class="t"><a href={d.url} target="_blank" rel="noreferrer" class="mono">#{d.n}</a> {d.title}</span><span /></div>)}
        </details>
      )}
      <form class="acts add-task" onSubmit={async (e) => {
        e.preventDefault();
        if (!task.trim()) return;
        if (await startRun({ step: "small-change", repo: f.epic!.repo, args: `${task.trim()}\n\nFile it as a child of epic #${f.epic!.n} (${f.epic!.key}).` }, "filing the task")) setTask("");
      }}>
        <input id="add-task" class="grow" placeholder="Add a task to this epic: describe it in a sentence" aria-label="Add a task to this epic" value={task} onInput={(e) => setTask((e.target as HTMLInputElement).value)} />
        <Btn small type="submit" disabled={!task.trim()}>Add task</Btn>
      </form>
    </>
  );
}

function PrdTab({ f }: { f: Feature }) {
  const [file, setFile] = useState<PRDFile | null>(null);
  const [err, setErr] = useState("");
  const [edit, setEdit] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [ask, setAsk] = useState("");
  const get = () => { setErr(""); setConflict(false); http.get<PRDFile>(`/api/prd?repo=${encodeURIComponent(f.product)}&path=${encodeURIComponent(f.path)}`).then(setFile, (e) => setErr(describeError(e))); };
  useEffect(get, [f.product, f.path]);
  const save = async () => {
    if (edit === null || !file) return;
    try {
      const nf = await http.send<PRDFile>("PUT", "/api/prd", { repo: file.repo, path: file.path, text: edit, base_sha: file.sha });
      setFile(nf); setEdit(null); toast(`Saved and committed on ${nf.branch || "the current branch"} (not pushed)`); void loadMany(["features"]);
    } catch (e) {
      const st = (e as { status?: number }).status;
      if (st === 409) setConflict(true);
      toast(describeError(e), "error");
    }
  };
  return (
    <>
      {err && <div class="banner bad" role="alert">{err}</div>}
      {conflict && <div class="banner bad" role="alert">The PRD changed on disk since you opened it. <Btn small onClick={() => { setEdit(null); get(); }}>Reload (drops your edit)</Btn></div>}
      <div class="acts">
        {edit === null
          ? <Btn small disabled={!file} onClick={() => setEdit(file!.text)}>Edit</Btn>
          : <><Btn small primary onClick={save}>Save and commit</Btn><Btn small onClick={async () => { if (edit === file?.text || (await askConfirm("Discard your edit?"))) setEdit(null); }}>Discard</Btn></>}
        <span class="dim">{file ? `${file.path}${file.branch ? ` on ${file.branch}` : ""}` : "Loading…"}{edit !== null ? " · saving commits only this file, it does not push" : ""}</span>
      </div>
      {file && (edit === null ? <div class="prd-read"><Markdown text={file.text} /></div>
        : <textarea class="mono prd-edit" aria-label="PRD markdown" value={edit} onInput={(e) => setEdit((e.target as HTMLTextAreaElement).value)} />)}
      <Pane label="ask claude to change it">
        <form class="form" onSubmit={async (e) => {
          e.preventDefault();
          if (!ask.trim()) return;
          const s = await startRun({ step: "create-prd", repo: f.product, product: f.product, args: `${f.path}\n\nUpdate this PRD: ${ask.trim()}` }, "the PRD update");
          if (s) { setAsk(""); nav(`#/sessions/${s.id}`); }
        }}>
          <textarea rows={3} aria-label="What should change in the PRD" placeholder="What should change? Claude updates the PRD and asks you when it is unsure." value={ask} onInput={(e) => setAsk((e.target as HTMLTextAreaElement).value)} />
          <div class="acts"><Btn small type="submit" disabled={!ask.trim()}>Start update</Btn></div>
        </form>
      </Pane>
    </>
  );
}

function ReviewTab({ f }: { f: Feature }) {
  const [offers, setOffers] = useState<ReviewOffers | null>(null);
  const [lenses, setLenses] = useState<string[] | null>(null);
  useEffect(() => { http.get<ReviewOffers>("/api/review/offers").then((o) => { setOffers(o); setLenses((l) => l ?? o.default); }, () => undefined); }, []);
  const full = f.panel ? (panels.value ?? []).find((p) => p.id === f.panel!.id) : undefined;
  useEffect(() => { if (f.panel && !full) void load("panels"); }, [f.panel?.id]);
  const docsPath = (products.value ?? []).find((p) => p.docs_repo === f.product)?.path;
  if (!f.panel || f.panel.state === "failed") {
    const list = offers?.kinds["create-prd"] ?? [];
    return (
      <div class="form">
        {f.panel?.state === "failed" && <div class="banner bad">The last review failed. Start a new one.</div>}
        <span class="mu">A panel of reviewers reads the PRD, each through one lens, and the PRD interview folds their notes in, round after round, until they approve or the round cap.</span>
        <div class="chips" role="group" aria-label="Lenses">
          {list.map((l) => { const on = (lenses ?? []).includes(l); return <button key={l} type="button" class={`chip${on ? " on" : ""}`} aria-pressed={on} onClick={() => setLenses(on ? lenses!.filter((x) => x !== l) : [...(lenses ?? []), l])}>{l}</button>; })}
        </div>
        <div class="acts">
          <Btn primary disabled={!lenses?.length || !docsPath} title={docsPath ? undefined : "the docs repo's checkout is not known"} onClick={() =>
            mutate(() => http.send("POST", "/api/review", { repo: f.product, artifact: `${docsPath}/${f.path}`, lenses }), "Peer review started", ["features", "panels"])}>Run the peer review panel</Btn>
          <span class="dim">{offers ? `up to ${offers.max_rounds} rounds` : ""}</span>
        </div>
      </div>
    );
  }
  const p = f.panel;
  const lensState = full?.status.lenses ?? {};
  return (
    <div class="form">
      <div class="dh"><Tag tone={p.state === "approved" ? "c-o" : p.state === "running" ? "c-q" : "c-w"}>{p.state}</Tag><b>Round {p.round} of {p.max_rounds}</b><span class="dim">{p.status.approved} of {p.status.total} lenses approve</span>
        {p.root_session && <a href={`#/sessions/${p.root_session}`}>PRD session</a>}</div>
      <div class="tablewrap"><table class="t"><thead><tr><th>Lens</th><th>Verdict</th><th /></tr></thead><tbody>
        {Object.entries(lensState).map(([l, v]) => (
          <tr key={l}><td>{l}</td><td><Tag tone={v === "approve" ? "c-o" : v === "failed" ? "c-b" : v === "changes" ? "c-w" : ""}>{v}</Tag></td>
            <td><div class="acts">
              {full?.lens_sessions[l] && <a href={`#/sessions/${full.lens_sessions[l]}`}>session</a>}
              <Btn small onClick={() => mutate(() => http.send("POST", `/api/review/${p.id}/lens`, { lens: l, action: "rerun" }), `Re-running ${l}`, ["panels", "features"])}>Re-run</Btn>
              <Btn small bad onClick={async () => { if (await askConfirm(`Drop the ${l} lens from this review?`)) await mutate(() => http.send("POST", `/api/review/${p.id}/lens`, { lens: l, action: "drop" }), `Dropped ${l}`, ["panels", "features"]); }}>Drop</Btn>
            </div></td></tr>
        ))}
        {!Object.keys(lensState).length && <tr><td colSpan={3} class="dim">Loading lenses…</td></tr>}
      </tbody></table></div>
      {(p.state === "cap reached" || p.state === "approved") && <div class="acts">{f.actions.filter((a) => a.label !== "Read PRD").map((a) => <Btn key={a.label} primary={a.primary} onClick={() => exec(a)}>{a.label}</Btn>)}</div>}
    </div>
  );
}

function SessionsTab({ f }: { f: Feature }) {
  if (!f.sessions.length) return <Empty>No sessions for this feature yet.</Empty>;
  return (
    <div class="rows">
      {f.sessions.map((s) => (
        <a key={s.id} class="row r5" href={`#/sessions/${s.id}`}>
          <span class={`tag ${statusTone(s.status)}`}>{s.status}</span><span class="t mono">{s.skill}</span><span class="t">{s.title}</span>
          <span class="w">{ago(s.started_at)}</span><span class="w mono">{fmtCost(s.cost)}</span>
        </a>
      ))}
    </div>
  );
}

export function FeaturePage() {
  const r = route.value;
  const slug = r.id!;
  const f = (features.value ?? []).filter((l) => !r.query.product || l.product.toLowerCase() === r.query.product.toLowerCase())
    .flatMap((l) => l.features).find((x) => x.slug === slug);
  const [more, setMore] = useState(false);
  if (!features.value) return <><Header title="Feature" /><Empty>Loading…</Empty></>;
  if (!f) return <><Header title="Feature"><Btn small onClick={() => nav("#/features")}>← Features</Btn></Header><Empty>No feature “{slug}” here. It may have been renamed. <a href="#/features">All features</a></Empty></>;
  const tab = (r.query.tab as Tab) || defaultTab(f);
  const closeEpic = f.epic && f.actions.find((a) => a.label === "Close epic");
  return (
    <>
      <nav class="crumbs" aria-label="Breadcrumb"><a href="#/features">Features</a> › <span>{f.title}</span></nav>
      <Header title={f.title} sub={<><a href={f.prd_route}>{f.path}</a>{f.epic && <> · <a href={f.epic.url} target="_blank" rel="noreferrer">epic {f.epic.key}</a></>}</>}>
        <span class="popw">
          <Btn small onClick={() => setMore(!more)}>More ▾</Btn>
          {more && (
            <div class="pop menu" onMouseLeave={() => setMore(false)}>
              <button type="button" class="pi" onClick={() => { setMore(false); nav(f.prd_route); }}>Read the PRD full page</button>
              {f.epic && <button type="button" class="pi" onClick={() => { setMore(false); setParam("tab", "issues", true); setTimeout(() => document.getElementById("add-task")?.focus(), 0); }}>Add a task</button>}
              {f.epic && <button type="button" class="pi c-b" onClick={async () => {
                setMore(false);
                if (closeEpic) { await exec(closeEpic); return; }
                const [o, n] = f.epic!.repo.split("/");
                if (await askConfirm(`Close epic #${f.epic!.n} and its ${f.counts.open} open issues as completed?`)) await mutate(() => http.send("POST", `/api/epics/${o}/${n}/${f.epic!.n}/close`, {}), "Epic closed", ["features"]);
              }}>Close epic and its issues</button>}
            </div>
          )}
        </span>
      </Header>
      <FeatureStrip f={f} link={false} />
      <BuildMap f={f} />
      <div class="chips" role="tablist" aria-label="Feature tabs">
        {TABS.map(([t, l]) => <button key={t} type="button" role="tab" aria-selected={tab === t} class={`chip${tab === t ? " on" : ""}`} onClick={() => setParam("tab", t, true)}>{l}{t === "issues" && f.counts.open ? ` ${f.counts.open}` : ""}{t === "sessions" && f.sessions.length ? ` ${f.sessions.length}` : ""}</button>)}
      </div>
      <Pane label={TABS.find(([t]) => t === tab)?.[1] ?? ""}>
        {tab === "issues" && <IssuesTab f={f} />}
        {tab === "prd" && <PrdTab f={f} />}
        {tab === "review" && <ReviewTab f={f} />}
        {tab === "sessions" && <SessionsTab f={f} />}
      </Pane>
    </>
  );
}
