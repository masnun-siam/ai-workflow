/** The old aiw ways to start work: the Create box (n) and the full Start dialog (command, where, input,
 *  model and effort, account). Both post StartRequest (API.md section 4) to POST /api/sessions. */
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { http } from "../api/http";
import type { RegistryStep } from "../api/extra";
import type { Effort, Model, OpenItem, PRD, ReviewOffers, Session, VaultFolder, VaultSuggestion } from "../api/types";
import { describeError } from "../state/actions";
import { currentRepo, load, loadMany, product, products, registry, repoList, repos, settings, status } from "../state/data";
import { nav } from "../state/route";
import { clock, shortRepo } from "../state/format";
import { createDraft, createOpen, paletteOpen, startReq, toast } from "../state/ui";
import { RepoField } from "./Shell";
import { Btn, Field, useFocusTrap } from "./ui";

export const MODELS: Model[] = ["opus", "sonnet", "haiku"];
export const EFFORTS: Effort[] = ["low", "medium", "high", "xhigh", "max"];
const FOLDER = ":folder";
const VAULT = ":vault";

// ---------- shared data, cached for the page's life ----------
let offersP: Promise<ReviewOffers> | null = null;
const offers = () => (offersP ??= http.get<ReviewOffers>("/api/review/offers").catch((e) => { offersP = null; throw e; }));
const openCache = new Map<string, Promise<OpenItem[]>>();
export function openItems(repo: string, kind: "issue" | "pr", fresh = false): Promise<OpenItem[]> {
  const k = `${repo}:${kind}`;
  if (fresh || !openCache.has(k)) {
    const p = http.get<{ items: OpenItem[] }>(`/api/repos/${repo}/open?kind=${kind}`).then((r) => r.items);
    p.catch(() => openCache.delete(k));
    openCache.set(k, p);
  }
  return openCache.get(k)!;
}

/** Word-overlap match against open issues: the old "Looks like #n" duplicate hint, done client side. */
const words = (t: string) => new Set(t.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length >= 4));
export function likelyDuplicate(text: string, items: OpenItem[]): OpenItem | null {
  const a = words(text);
  if (a.size < 2) return null;
  let best: OpenItem | null = null, score = 0;
  for (const it of items) {
    const b = words(it.title);
    if (!b.size) continue;
    let common = 0;
    for (const w of b) if (a.has(w)) common++;
    const s = common / Math.min(a.size, b.size);
    if (common >= 2 && s > score) { score = s; best = it; }
  }
  return score >= 0.5 ? best : null;
}

/** "limited until 14:05" for an account label, or "". */
function limitNote(label: string): string {
  const u = status.value?.usage.find((x) => x.label === label);
  const t = u?.limit.limited_until;
  return t && t * 1000 > Date.now() ? `limited until ${clock(t)}` : "";
}

function AccountPick({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const list = settings.value?.commands ?? [];
  if (list.length < 2) return null;
  const def = settings.value?.default ?? list[0]?.label ?? "";
  return (
    <fieldset class="fset"><legend>Run on</legend>
      <div class="acts">
        {list.map((c) => {
          const note = limitNote(c.label);
          return (
            <label key={c.label} class={`opt inline${(value || def) === c.label ? " on" : ""}`}>
              <input type="radio" name="acct" checked={(value || def) === c.label} onChange={() => onChange(c.label)} />
              <span><b>{c.label}</b>{c.label === def && <span class="dim"> default</span>}{note && <small class="c-w"> {note}</small>}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function LensPick({ kind, value, onChange, label = "Review it with" }: { kind: string; value: string[]; onChange: (v: string[]) => void; label?: string }) {
  const [o, setO] = useState<ReviewOffers | null>(null);
  useEffect(() => { void offers().then(setO).catch(() => setO(null)); }, []);
  const list = o?.kinds[kind] ?? [];
  if (!list.length) return null;
  return (
    <fieldset class="fset"><legend>{label} <span class="dim">(peer-review lenses, optional)</span></legend>
      <div class="chips">
        {list.map((l) => {
          const on = value.includes(l);
          return <button key={l} type="button" class={`chip${on ? " on" : ""}`} aria-pressed={on} onClick={() => onChange(on ? value.filter((x) => x !== l) : [...value, l])}>{l}</button>;
        })}
      </div>
    </fieldset>
  );
}

async function start(body: Record<string, unknown>, label: string): Promise<boolean> {
  try {
    const s = await http.send<Session>("POST", "/api/sessions", { ...body, guard: true });
    toast(s.status === "queued" ? `Queued ${label}` : `Started ${label}`);
    void loadMany(["sessions", "inbox"]);
    nav(`#/sessions/${s.id}`);
    return true;
  } catch (e) {
    const f = e as { body?: { href?: string } };
    toast(describeError(e), "error", f.body?.href);
    return false;
  }
}

function Dialog({ label, onClose, children, wide }: { label: string; onClose: () => void; children: preact.ComponentChildren; wide?: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div class={`dlg${wide ? " wide" : ""}`} ref={box} role="dialog" aria-modal="true" aria-label={label}>{children}</div>
    </div>
  );
}

// ---------- Create box ----------
type Route = "feature" | "small";
const PRIORITIES = ["P1", "P2", "P3"];

export function CreateDialog() {
  const [route, setRoute] = useState<Route>("feature");
  const [repo, setRepo] = useState(currentRepo.value ?? repoList.value[0]?.slug ?? "");
  const [account, setAccount] = useState("");
  const [lenses, setLenses] = useState<string[]>([]);
  const [prio, setPrio] = useState("P2");
  const [dup, setDup] = useState<OpenItem | null>(null);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => ref.current?.focus(), []);
  useEffect(() => { void offers().then((o) => setLenses(o.default)).catch(() => undefined); }, []);
  const text = createDraft.value;
  useEffect(() => {
    setDup(null);
    if (text.trim().length < 20 || !repo) return;
    const t = setTimeout(() => { void openItems(repo, "issue").then((items) => setDup(likelyDuplicate(text, items))).catch(() => undefined); }, 800);
    return () => clearTimeout(t);
  }, [text, repo]);
  const close = () => (createOpen.value = false);
  const submit = async () => {
    if (!text.trim() || !repo || busy) return;
    setBusy(true);
    const common = { repo, account: account || undefined, pin_account: account ? true : undefined };
    const ok = route === "feature"
      // planning runs use opus at medium effort and never touch the saved defaults (old aiw PLAN_RUN)
      ? await start({ step: "create-prd", args: text.trim(), lenses: lenses.length ? lenses : undefined, model: "opus", effort: "medium", ...common }, "the PRD interview")
      : await start({ step: "small-change", args: `${text.trim()}\n\nPriority: ${prio}`, ...common }, "filing the small change");
    setBusy(false);
    if (ok) { createDraft.value = ""; close(); if (route === "small") toast("Filing it: it shows up on Small changes once refined"); }
  };
  const noRepos = repos.value && !repoList.value.length;
  return (
    <Dialog label="What should change?" onClose={close}>
      <form class="form" onSubmit={(e) => { e.preventDefault(); void submit(); }}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void submit(); } }}>
        <h2 class="dlg-h">What should change?</h2>
        <textarea ref={ref} rows={5} aria-label="Describe the change" placeholder="Describe a feature or a fix in a few sentences…" value={text}
          onInput={(e) => (createDraft.value = (e.target as HTMLTextAreaElement).value)} />
        {dup && <div class="banner inline" role="status">Looks like <a href={dup.url ?? `https://github.com/${repo}/issues/${dup.number}`} target="_blank" rel="noreferrer">#{dup.number} {dup.title}</a>. Check it before filing a new one.</div>}
        <div class="seg" role="radiogroup" aria-label="Route">
          {([["feature", "Feature", "a PRD interview, then tasks and a dispatch"], ["small", "Small change", "one issue, no PRD"]] as [Route, string, string][]).map(([v, l, d]) => (
            <button key={v} type="button" role="radio" aria-checked={route === v} class={`seg-o${route === v ? " on" : ""}`} onClick={() => setRoute(v)}><b>{l}</b><small class="dim">{d}</small></button>
          ))}
        </div>
        <div class="fields">
          <Field label="Repository">{noRepos ? <span class="c-w">No repositories yet. <a href="#/onboarding">Add one</a>.</span> : <RepoField label="Repository" value={repo} onChange={setRepo} />}</Field>
          {route === "small" && <Field label="Priority"><select value={prio} onChange={(e) => setPrio((e.target as HTMLSelectElement).value)}>{PRIORITIES.map((p) => <option key={p}>{p}</option>)}</select></Field>}
        </div>
        {route === "feature" && <LensPick kind="create-prd" value={lenses} onChange={setLenses} label="Review the PRD with" />}
        <AccountPick value={account} onChange={setAccount} />
        <div class="acts">
          <Btn type="submit" primary disabled={busy || !text.trim() || !repo}>{busy ? "Starting…" : route === "feature" ? "Start the PRD interview" : "File the issue"}</Btn>
          <Btn onClick={close}>Cancel</Btn>
          <span class="grow" />
          <Btn small onClick={() => { close(); paletteOpen.value = true; }}>Run a command instead</Btn>
        </div>
        <span class="dim"><kbd>⌘⏎</kbd>start · the text stays if you cancel</span>
      </form>
    </Dialog>
  );
}

// ---------- Start dialog ----------
const STAGES: [string, string][] = [["prd", "Plan"], ["tasks", "Plan"], ["refine", "Plan"], ["implement", "Build"], ["review", "Review"], ["release", "Ship"], ["notify", "Ship"], ["ops", "Maintain"], ["me", "Capture"]];
const GROUP_ORDER = ["Plan", "Build", "Review", "Ship", "Capture", "Maintain"];
const groupOf = (s: RegistryStep) => STAGES.find(([st]) => s.stage.split(",")[0] === st)?.[1] ?? "Maintain";
/** Steps whose argument is an open issue or PR of the repo (old OpenPicker). */
const PICK: Record<string, { kind: "issue" | "pr"; url?: boolean }> = {
  "implement-issue": { kind: "issue" }, "refine-issues": { kind: "issue" }, "reproduce-bug": { kind: "issue" }, "after-merge": { kind: "issue" },
  "pr-review": { kind: "pr" }, "pr-grind": { kind: "pr", url: true },
};

function OpenPicker({ repo, kind, onPick }: { repo: string; kind: "issue" | "pr"; onPick: (it: OpenItem) => void }) {
  const [items, setItems] = useState<OpenItem[] | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const get = (fresh = false) => { setItems(null); setErr(""); openItems(repo, kind, fresh).then(setItems, (e) => setErr(describeError(e))); };
  useEffect(() => { if (repo && !repo.startsWith("/")) get(); }, [repo, kind]);
  if (!repo || repo.startsWith("/")) return null;
  const s = q.trim().toLowerCase();
  const shown = (items ?? []).filter((it) => !s || `#${it.number} ${it.title}`.toLowerCase().includes(s)).slice(0, 50);
  return (
    <div class="picker">
      <div class="acts"><input type="search" placeholder={`Filter open ${kind === "pr" ? "pull requests" : "issues"} of ${shortRepo(repo)}`} aria-label="Filter" value={q} onInput={(e) => setQ((e.target as HTMLInputElement).value)} /><Btn small onClick={() => get(true)}>Refresh</Btn></div>
      {err && <div class="c-b">{err}</div>}
      {!items && !err && <div class="dim">Loading from GitHub…</div>}
      <div class="picker-list" role="listbox" aria-label={`Open ${kind}s`}>
        {shown.map((it) => (
          <button key={it.number} type="button" role="option" aria-selected={false} class="pi" onClick={() => onPick(it)}>
            <span class="mono dim">#{it.number}</span><span class="t">{it.title}</span>{it.draft && <span class="r">draft</span>}
          </button>
        ))}
        {items && !shown.length && <div class="dim">None open{s ? " that match" : ""}.</div>}
      </div>
    </div>
  );
}

function PrdPick({ prod, onPick }: { prod: string; onPick: (path: string) => void }) {
  const [list, setList] = useState<PRD[] | null>(null);
  useEffect(() => { if (prod) http.get<{ prds: PRD[] }>(`/api/products/${prod}/prds`).then((r) => setList(r.prds), () => setList([])); }, [prod]);
  const approved = (list ?? []).filter((p) => p.status === "Approved");
  if (!list || !approved.length) return null;
  return (
    <div class="picker"><span class="dim">Approved PRDs</span>
      <div class="picker-list">{approved.map((p) => <button key={p.path} type="button" class="pi" onClick={() => onPick(p.path)}><span class="t">{p.title}</span><span class="r mono">{p.label}</span></button>)}</div>
    </div>
  );
}

/** Vault folder for a no-repo run: Project / Feature under 05-Work, with Suggest with Claude. */
function FolderChooser({ text, value, onChange }: { text: string; value: string; onChange: (v: string) => void }) {
  const [folders, setFolders] = useState<VaultFolder[]>([]);
  const [sug, setSug] = useState<VaultSuggestion | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { http.get<{ folders: VaultFolder[] }>("/api/vault/folders").then((r) => setFolders(r.folders ?? []), () => setFolders([])); }, []);
  const [project = "", feature = ""] = value.replace(/^05-Work\/?/, "").split("/");
  const set = (p: string, f: string) => onChange(p ? `05-Work/${p}${f ? `/${f}` : ""}` : "");
  const projects = [...new Set(folders.map((f) => f.project))];
  const feats = folders.filter((f) => f.project === project && f.feature).map((f) => f.feature!);
  return (
    <div class="fields">
      <Field label="Project"><input list="vault-projects" value={project} onInput={(e) => set((e.target as HTMLInputElement).value, feature)} /><datalist id="vault-projects">{projects.map((p) => <option key={p} value={p} />)}</datalist></Field>
      <Field label="Feature (optional)"><input list="vault-feats" value={feature} onInput={(e) => set(project, (e.target as HTMLInputElement).value)} /><datalist id="vault-feats">{feats.map((f) => <option key={f} value={f} />)}</datalist></Field>
      <div class="fld"><span>&nbsp;</span><Btn small disabled={busy || text.trim().length < 10} onClick={async () => {
        setBusy(true);
        try { const s = await http.send<VaultSuggestion>("POST", "/api/vault/suggest", { text }); setSug(s); set(s.project, s.feature); } catch (e) { toast(describeError(e), "error"); }
        setBusy(false);
      }}>{busy ? "Thinking…" : "Suggest with Claude"}</Btn></div>
      {sug && <small class="dim" style={{ flexBasis: "100%" }}>{sug.new_project ? "new project · " : ""}{sug.new_feature ? "new feature · " : ""}{sug.why}</small>}
    </div>
  );
}

export function StartDialog() {
  const req = startReq.value!;
  const steps = registry.value;
  const [stepId, setStepId] = useState<string | null>(req.step?.id ?? null);
  const step = steps.find((s) => s.id === stepId) ?? null;
  const [args, setArgs] = useState(req.args ?? "");
  const [where, setWhere] = useState(req.repo ?? currentRepo.value ?? repoList.value[0]?.slug ?? "");
  const [folder, setFolder] = useState("");
  const [vault, setVault] = useState("");
  const [prod, setProd] = useState(product.value ?? products.value?.[0]?.docs_repo ?? "");
  const [issue, setIssue] = useState<number | null>(null);
  const [model, setModel] = useState<string>(settings.value?.run_model ?? "");
  const [effort, setEffort] = useState<string>(settings.value?.run_effort ?? "");
  const [remember, setRemember] = useState(false);
  const [lenses, setLenses] = useState<string[]>([]);
  const [account, setAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => ref.current?.focus(), [stepId]);
  useEffect(() => { if (!settings.value) void load("settings"); }, []);

  const runsIn = step ? step.runs_in : "custom";
  const pick = step ? PICK[step.id] : undefined;
  const repoVal = where === FOLDER ? folder.trim() : where;
  const groups = useMemo(() => {
    const m = new Map<string, RegistryStep[]>();
    for (const s of steps) m.set(groupOf(s), [...(m.get(groupOf(s)) ?? []), s]);
    return GROUP_ORDER.filter((g) => m.has(g)).map((g) => [g, m.get(g)!] as const);
  }, [steps]);
  const lensKind = !step ? "custom" : step.id === "create-prd" ? "create-prd" : "";
  const acctLabel = account || settings.value?.default || "";
  const limited = !!acctLabel && !!limitNote(acctLabel);
  const missing = runsIn === "custom" ? !args.trim() || (where === FOLDER && !folder.trim()) || (!where && where !== VAULT)
    : runsIn === "issue" || runsIn === "repo" ? !repoVal
    : runsIn === "docs" ? !prod : false;

  const choose = (s: RegistryStep | null) => {
    if (s && !s.available) { toast(s.reason ?? `${s.id} is not available`, "warn"); return; }
    setStepId(s?.id ?? null); setIssue(null); setLenses([]);
    if (where === VAULT && s) setWhere(currentRepo.value ?? "");
  };
  const submit = async () => {
    if (missing || busy) return;
    const body: Record<string, unknown> = step ? { step: step.id, args: args.trim() || undefined } : { text: args };
    if (runsIn === "docs") body.product = prod;
    else if (runsIn === "custom" && where === VAULT) { body.no_repo = true; if (vault) body.vault_folder = vault; }
    else if (runsIn !== "none" && repoVal) body.repo = repoVal;
    if (issue) body.issue = issue;
    if (model) body.model = model;
    if (effort) body.effort = effort;
    if (lenses.length) body.lenses = lenses;
    if (account) { body.account = account; body.pin_account = true; }
    setBusy(true);
    if (remember && (model !== (settings.value?.run_model ?? "") || effort !== (settings.value?.run_effort ?? ""))) {
      try { await http.send("PUT", "/api/settings", { run_model: model || null, run_effort: effort || null }); void load("settings"); } catch (e) { toast(describeError(e), "error"); }
    }
    const ok = await start(body, step?.id ?? "the prompt");
    setBusy(false);
    if (ok) startReq.value = null;
  };
  const close = () => (startReq.value = null);
  const repoExtras = runsIn === "custom" ? [{ value: FOLDER, label: "Another folder…" }, { value: VAULT, label: "No repo yet: notes vault" }] : [{ value: FOLDER, label: "Another folder…" }];

  return (
    <Dialog label="What should we start?" onClose={close} wide>
      <div class="start">
        <nav class="start-cmds" aria-label="Commands">
          {groups.map(([g, list]) => (
            <div key={g} role="group" aria-label={g}>
              <div class="gh">{g}</div>
              {list.map((s) => (
                <button key={s.id} type="button" class={`pi${s.id === stepId ? " sel" : ""}${s.available ? "" : " off"}`} aria-current={s.id === stepId} title={s.reason ?? s.args_hint} onClick={() => choose(s)}>
                  {s.label ?? s.id}{s.source === "setu" && <span class="r">setu</span>}
                </button>
              ))}
            </div>
          ))}
          <div class="gh">Other</div>
          <button type="button" class={`pi${!stepId ? " sel" : ""}`} aria-current={!stepId} onClick={() => choose(null)}>Custom prompt</button>
        </nav>
        <form class="form start-form" onSubmit={(e) => { e.preventDefault(); void submit(); }}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void submit(); } }}>
          <h2 class="dlg-h">{step ? <>{step.label ?? step.id} <span class="dim mono">/{step.source === "blubird" ? "blubird:" : ""}{step.skill}</span></> : "Custom prompt"}</h2>
          {!step && <div class="banner">A custom prompt runs headless with your saved permissions. Say exactly what Claude may change.</div>}

          {(runsIn === "issue" || runsIn === "repo" || runsIn === "custom") && (
            <Field label="Where">
              <RepoField label="Where" value={where} onChange={(v) => { setWhere(v); setIssue(null); }} extrasAfter={repoExtras} />
            </Field>
          )}
          {where === FOLDER && runsIn !== "docs" && runsIn !== "none" && (
            <div class="acts">
              <input class="grow mono" placeholder="/absolute/path/to/a/git/checkout" aria-label="Folder" value={folder} onInput={(e) => setFolder((e.target as HTMLInputElement).value)} />
              {repos.value?.can_browse && <Btn small onClick={async () => { try { const r = await http.send<{ path: string | null }>("POST", "/api/repos/browse", { start: folder || undefined }); if (r.path) setFolder(r.path); } catch (e) { toast(describeError(e), "error"); } }}>Browse…</Btn>}
            </div>
          )}
          {runsIn === "custom" && where === VAULT && <FolderChooser text={args} value={vault} onChange={setVault} />}
          {runsIn === "docs" && (
            <Field label="Product (docs repo)">
              {(products.value ?? []).length ? <select value={prod} onChange={(e) => setProd((e.target as HTMLSelectElement).value)}>{products.value!.map((p) => <option key={p.docs_repo} value={p.docs_repo}>{p.name} · {p.docs_repo}</option>)}</select>
                : <span class="c-w">No product yet. Add a docs repo in <a href="#/settings?pane=products">Settings → products and repos</a>.</span>}
            </Field>
          )}

          <Field label={step ? `Input${step.args_hint ? `: ${step.args_hint}` : ""}` : "Prompt"}>
            <textarea ref={ref} rows={step ? 2 : 5} placeholder={step ? (step.args_hint ?? "optional") : "What should Claude do?"} value={args}
              onInput={(e) => { setArgs((e.target as HTMLTextAreaElement).value); setIssue(null); }} />
          </Field>
          {pick && <OpenPicker repo={repoVal} kind={pick.kind} onPick={(it) => { setArgs(pick.url && it.url ? it.url : String(it.number)); setIssue(pick.kind === "issue" ? it.number : null); }} />}
          {step?.id === "create-tasks" && <PrdPick prod={prod} onPick={setArgs} />}
          {lensKind && <LensPick kind={lensKind} value={lenses} onChange={setLenses} label="Also open a peer review with" />}

          <div class="fields">
            <Field label="Model"><select value={model} onChange={(e) => setModel((e.target as HTMLSelectElement).value)}><option value="">default</option>{MODELS.map((m) => <option key={m}>{m}</option>)}</select></Field>
            <Field label="Effort"><select value={effort} onChange={(e) => setEffort((e.target as HTMLSelectElement).value)}><option value="">default</option>{EFFORTS.map((m) => <option key={m}>{m}</option>)}</select></Field>
            <label class="fld check"><span>&nbsp;</span><span><input type="checkbox" checked={remember} onChange={(e) => setRemember((e.target as HTMLInputElement).checked)} /> Make these the default</span></label>
          </div>
          <AccountPick value={account} onChange={setAccount} />
          <div class="acts">
            <Btn type="submit" primary disabled={busy || missing}>{busy ? "Starting…" : limited ? "Queue" : "Start"}</Btn>
            <Btn onClick={close}>Cancel</Btn>
            {limited && <span class="c-w">{acctLabel} is {limitNote(acctLabel)}: it starts when the limit resets.</span>}
          </div>
        </form>
      </div>
    </Dialog>
  );
}
