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
import { Btn, Field } from "./ui";

export function matchSteps(steps: RegistryStep[], q: string): RegistryStep[] {
  const s = q.trim().toLowerCase();
  return steps.filter((x) => `${x.id} ${x.skill} ${x.source}`.toLowerCase().includes(s));
}

export function Palette() {
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => ref.current?.focus(), []);
  const list = matchSteps(registry.value, q);
  const total = list.length + (q.trim() ? 1 : 0);
  const pick = (n: number) => {
    paletteOpen.value = false;
    if (n < list.length) startReq.value = { step: list[n]! };
    else if (q.trim()) startReq.value = { step: null, args: q.trim() };
  };
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) paletteOpen.value = false; }}>
      <div class="dlg" role="dialog" aria-modal="true" aria-label="Run a skill">
        <input ref={ref} role="combobox" aria-expanded="true" aria-controls="pal-list" placeholder="Run a skill…" aria-label="Search skills" value={q}
          onInput={(e) => { setQ((e.target as HTMLInputElement).value); setI(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { setI(clamp(i + 1, 0, total - 1)); e.preventDefault(); }
            else if (e.key === "ArrowUp") { setI(clamp(i - 1, 0, total - 1)); e.preventDefault(); }
            else if (e.key === "Enter") { pick(i); e.preventDefault(); }
          }} />
        <div id="pal-list" role="listbox">
          {list.map((s, n) => (
            <button key={s.id} type="button" role="option" aria-selected={n === i} class={`pi${n === i ? " sel" : ""}`} disabled={!s.available} title={s.reason} onClick={() => pick(n)}>
              <span class="c-w">/</span>{s.source === "blubird" ? "blubird:" : ""}{s.id}<span class="r">{s.available ? s.runs_in : (s.reason ?? "unavailable")}</span>
            </button>
          ))}
          {q.trim() && <button type="button" role="option" aria-selected={i === list.length} class={`pi${i === list.length ? " sel" : ""}`} onClick={() => pick(list.length)}>Run as free text: {q.trim()}</button>}
        </div>
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
  useEffect(() => ref.current?.focus(), []);
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
      <form class="dlg" aria-modal="true" aria-label="Start a run" style={{ padding: "14px", display: "flex", flexDirection: "column", gap: "10px" }} onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <b>{step ? `${step.source === "blubird" ? "blubird:" : ""}${step.id}` : "Free text run"}</b>
        {step?.args_hint && <span class="dim">{step.args_hint}</span>}
        {needsRepo && (
          <Field label="Repository">
            <select value={repo} onChange={(e) => setRepo((e.target as HTMLSelectElement).value)}>{(repos.value?.repos ?? []).map((r) => <option key={r.slug}>{r.slug}</option>)}</select>
          </Field>
        )}
        {step?.runs_in === "docs" && (
          <Field label="Product"><select value={prod} onChange={(e) => setProd((e.target as HTMLSelectElement).value)}>{(products.value ?? []).map((p) => <option key={p.docs_repo} value={p.docs_repo}>{p.name}</option>)}</select></Field>
        )}
        <Field label={step ? "Arguments" : "Prompt"}><input ref={ref} value={args} onInput={(e) => setArgs((e.target as HTMLInputElement).value)} /></Field>
        {(settings.value?.commands.length ?? 0) > 1 && (
          <Field label="Account"><select value={account} onChange={(e) => setAccount((e.target as HTMLSelectElement).value)}><option value="">default</option>{settings.value!.commands.map((c) => <option key={c.label}>{c.label}</option>)}</select></Field>
        )}
        <div class="acts"><Btn type="submit" primary disabled={busy || (!step && !args.trim())}>Start</Btn><Btn onClick={() => (startReq.value = null)}>Cancel</Btn></div>
      </form>
    </div>
  );
}

export function ConfirmDialog() {
  const c = confirmReq.value!;
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) c.resolve(false); }}>
      <div class="dlg" role="alertdialog" aria-modal="true" aria-label="Confirm" style={{ padding: "14px", display: "flex", flexDirection: "column", gap: "10px" }}
        onKeyDown={(e) => { if (e.key === "y") c.resolve(true); else if (e.key === "n") c.resolve(false); }}>
        <span>{c.text}</span>
        <div class="acts"><button ref={ref} type="button" class="btn pri" onClick={() => c.resolve(true)}><kbd>y</kbd>Yes</button><Btn k="n" onClick={() => c.resolve(false)}>No</Btn></div>
      </div>
    </div>
  );
}

const GLOBAL: [string, string][] = [["1-7", "switch screen"], [": or ⌘K", "run a skill"], ["⏎", "open selected"], ["esc", "close"], ["a/b/c", "answer a question"], ["letters on buttons", "run that action"],
  [".", "mode: system / dark / light"], ["s", "look: console / river"], ["L", "layout: drawer / split"], ["?", "this help"]];
export function Help() {
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) helpOpen.value = false; }}>
      <div class="dlg" role="dialog" aria-modal="true" aria-label="Keyboard help">
        <div class="help">{GLOBAL.map(([k, d]) => <><kbd>{k}</kbd><span>{d}</span></>)}
          {Object.entries(HINTS).filter(([s]) => s !== "prd").map(([s, hs]) => <><kbd>{s}</kbd><span>{hs.map(([k, d]) => `${k} ${d}`).join(" · ")}</span></>)}</div>
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
    </div>
  );
}
