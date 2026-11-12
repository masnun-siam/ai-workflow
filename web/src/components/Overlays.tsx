import { useEffect, useRef, useState } from "preact/hooks";
import { http } from "../api/http";
import type { RegistryStep } from "../api/extra";
import type { Session } from "../api/types";
import { describeError } from "../state/actions";
import { loadMany, products, registry, repos, settings } from "../state/data";
import { nav } from "../state/route";
import { confirmReq, helpOpen, paletteOpen, startReq, toast, toastMsg } from "../state/ui";
import { clamp } from "../state/ui";
import { HINTS } from "../state/keymap";
import { Btn, Field, useFocusTrap } from "./ui";

const RUNS_IN: Record<string, string> = { docs: "in a docs repo", issue: "on an issue", repo: "in a repo", none: "no repo needed" };

export function matchSteps(steps: RegistryStep[], q: string): RegistryStep[] {
  const s = q.trim().toLowerCase();
  return steps.filter((x) => `${x.id} ${x.skill} ${x.source}`.toLowerCase().includes(s));
}

export function Palette() {
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const ref = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);
  useEffect(() => ref.current?.focus(), []);
  useEffect(() => { document.querySelector("#pal-list .sel")?.scrollIntoView?.({ block: "nearest" }); }, [i]);
  const list = matchSteps(registry.value, q);
  const total = list.length + (q.trim() ? 1 : 0);
  const pick = (n: number) => {
    const step = list[n];
    if (step && !step.available) { toast(step.reason ?? `${step.id} is not available`, "warn"); return; }
    paletteOpen.value = false;
    if (step) startReq.value = { step };
    else if (q.trim()) startReq.value = { step: null, args: q.trim() };
  };
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) paletteOpen.value = false; }}>
      <div class="dlg" ref={box} role="dialog" aria-modal="true" aria-label="Run a skill">
        <input ref={ref} class="pal-q" role="combobox" aria-activedescendant={total ? `pal-${i}` : undefined} aria-expanded="true" aria-controls="pal-list" placeholder="Search skills, or type a prompt to run as free text…" aria-label="Search skills" value={q}
          onInput={(e) => { setQ((e.target as HTMLInputElement).value); setI(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { setI(clamp(i + 1, 0, total - 1)); e.preventDefault(); }
            else if (e.key === "ArrowUp") { setI(clamp(i - 1, 0, total - 1)); e.preventDefault(); }
            else if (e.key === "Enter") { pick(i); e.preventDefault(); }
          }} />
        <div id="pal-list" role="listbox">
          {list.map((s, n) => (
            <button key={s.id} id={`pal-${n}`} type="button" role="option" aria-selected={n === i} aria-disabled={!s.available} class={`pi${n === i ? " sel" : ""}${s.available ? "" : " off"}`} title={s.reason} onMouseMove={() => n !== i && setI(n)} onClick={() => pick(n)}>
              <span class="c-w">/</span>{s.source === "blubird" ? "blubird:" : ""}{s.id}<span class="r">{s.available ? RUNS_IN[s.runs_in] ?? s.runs_in : (s.reason ?? "unavailable")}</span>
            </button>
          ))}
          {!list.length && !q.trim() && <div class="empty">No skills loaded yet.</div>}
          {q.trim() && <button id={`pal-${list.length}`} type="button" role="option" aria-selected={i === list.length} class={`pi${i === list.length ? " sel" : ""}`} onClick={() => pick(list.length)}><span class="c-w">›</span>Run as free text: <b>{q.trim()}</b><span class="r">{list.length ? "" : "no skill matches"}</span></button>}
        </div>
        <div class="dlg-foot"><span><kbd>↑↓</kbd>move</span><span><kbd>⏎</kbd>choose</span><span><kbd>esc</kbd>close</span></div>
      </div>
    </div>
  );
}

export function StartDialog() {
  const req = startReq.value!;
  const step = req.step;
  const [args, setArgs] = useState(req.args ?? "");
  const [repo, setRepo] = useState(req.repo ?? repos.value?.repos[0]?.slug ?? "");
  const [prod, setProd] = useState(products.value?.[0]?.docs_repo ?? "");
  const [account, setAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);
  useEffect(() => ref.current?.focus(), []);
  const repoList = repos.value?.repos ?? [];
  const needsRepo = !step || step.runs_in === "issue" || step.runs_in === "repo";
  const submit = async () => {
    const body: Record<string, unknown> = step ? { step: step.id, args: args || undefined } : { text: args };
    if (step?.runs_in === "docs") body.product = prod;
    else if (needsRepo && repo) body.repo = repo;
    if (account) body.account = account;
    body.guard = true;
    setBusy(true);
    try {
      const s = await http.send<Session>("POST", "/api/sessions", body);
      startReq.value = null;
      toast(`Started ${step?.id ?? "run"}`);
      void loadMany(["sessions"]);
      nav(`#/sessions/${s.id}`);
    } catch (e) {
      const f = e as { body?: { href?: string } };
      toast(describeError(e), "error", f.body?.href);
      setBusy(false);
    }
  };
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) startReq.value = null; }}>
      <div class="dlg" ref={box} role="dialog" aria-modal="true" aria-labelledby="start-h"><form class="form" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <h2 id="start-h" class="dlg-h">{step ? `Run ${step.source === "blubird" ? "blubird:" : ""}${step.id}` : "Run a free text prompt"}</h2>
        {step?.args_hint && <span class="dim">Arguments: {step.args_hint}</span>}
        {needsRepo && (
          <Field label="Repository">
            {repoList.length ? <select value={repo} onChange={(e) => setRepo((e.target as HTMLSelectElement).value)}>{repoList.map((r) => <option key={r.slug}>{r.slug}</option>)}</select>
              : <span class="c-w">No repositories are registered yet. Add one in Settings → products and repos.</span>}
          </Field>
        )}
        {step?.runs_in === "docs" && (
          <Field label="Product"><select value={prod} onChange={(e) => setProd((e.target as HTMLSelectElement).value)}>{(products.value ?? []).map((p) => <option key={p.docs_repo} value={p.docs_repo}>{p.name}</option>)}</select></Field>
        )}
        <Field label={step ? "Arguments (optional)" : "Prompt"}><input ref={ref} placeholder={step ? (step.args_hint ?? "") : "What should Claude do?"} value={args} onInput={(e) => setArgs((e.target as HTMLInputElement).value)} /></Field>
        {(settings.value?.commands.length ?? 0) > 1 && (
          <Field label="Account"><select value={account} onChange={(e) => setAccount((e.target as HTMLSelectElement).value)}><option value="">default</option>{settings.value!.commands.map((c) => <option key={c.label}>{c.label}</option>)}</select></Field>
        )}
        <div class="acts"><Btn type="submit" primary disabled={busy || (!step && !args.trim()) || (needsRepo && !!step && !repo)}>{busy ? "Starting…" : "Start"}</Btn><Btn onClick={() => (startReq.value = null)}>Cancel</Btn></div>
      </form></div>
    </div>
  );
}

export function ConfirmDialog() {
  const c = confirmReq.value!;
  const ref = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);
  useEffect(() => ref.current?.focus(), []);
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) c.resolve(false); }}>
      <div class="dlg form narrow" ref={box} role="alertdialog" aria-modal="true" aria-labelledby="confirm-t"
        onKeyDown={(e) => { if (e.key === "y") c.resolve(true); else if (e.key === "n") c.resolve(false); }}>
        <span id="confirm-t">{c.text}</span>
        <div class="acts"><button ref={ref} type="button" class="btn pri" onClick={() => c.resolve(true)}><kbd>y</kbd>Yes</button><Btn k="n" onClick={() => c.resolve(false)}>No</Btn></div>
      </div>
    </div>
  );
}

const GLOBAL: [string, string][] = [["1-7", "switch screen"], [": or ⌘K", "run a skill"], ["⏎", "open selected"], ["esc", "close"], ["a/b/c", "answer a question"], ["letters on buttons", "run that action"],
  [".", "mode: system / dark / light"], ["s", "look: classic / console / river"], ["L", "layout: drawer / split"], ["?", "this help"]];
export function Help() {
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box, true);
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) helpOpen.value = false; }}>
      <div class="dlg" ref={box} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="help-h">
        <div class="dlg-top"><h2 id="help-h" class="dlg-h">Keyboard shortcuts</h2><Btn k="esc" small onClick={() => (helpOpen.value = false)}>close</Btn></div>
        <div class="help">{GLOBAL.map(([k, d]) => <><kbd>{k}</kbd><span>{d}</span></>)}
          <h3 class="gh help-sep">On each screen</h3>
          {Object.entries(HINTS).filter(([s]) => s !== "prd").map(([s, hs]) => <><b class="help-scr">{s}</b><span>{hs.map(([k, d]) => `${k} ${d}`).join(" · ")}</span></>)}</div>
      </div>
    </div>
  );
}

export function Toast() {
  const t = toastMsg.value;
  if (!t) return null;
  return (
    <div class={`toast ${t.level}`} role={t.level === "error" ? "alert" : "status"}>
      {t.msg}
      {t.path && <button type="button" onClick={() => { nav(t.path!); toastMsg.value = null; }}>Open</button>}
      <button type="button" aria-label="Dismiss" onClick={() => (toastMsg.value = null)}>×</button>
    </div>
  );
}
