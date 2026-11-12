import { useEffect, useRef, useState } from "preact/hooks";
import type { RegistryStep } from "../api/extra";
import { registry } from "../state/data";
import { nav } from "../state/route";
import { confirmReq, helpOpen, openCreate, paletteOpen, startReq, toast, toastMsg } from "../state/ui";
import { clamp } from "../state/ui";
import { HINTS } from "../state/keymap";
import { Btn, useFocusTrap } from "./ui";

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
          <button type="button" class="pi" onClick={() => { paletteOpen.value = false; openCreate(q.trim() || undefined); }}><span class="c-w">+</span>Describe a feature or a fix{q.trim() ? <>: <b>{q.trim()}</b></> : null}<span class="r"><kbd>n</kbd></span></button>
          {q.trim() && <button id={`pal-${list.length}`} type="button" role="option" aria-selected={i === list.length} class={`pi${i === list.length ? " sel" : ""}`} onClick={() => pick(list.length)}><span class="c-w">›</span>Run as free text: <b>{q.trim()}</b><span class="r">{list.length ? "" : "no skill matches"}</span></button>}
        </div>
        <div class="dlg-foot"><span><kbd>↑↓</kbd>move</span><span><kbd>⏎</kbd>choose</span><span><kbd>esc</kbd>close</span></div>
      </div>
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

const GLOBAL: [string, string][] = [["1-9, 0", "go to a page"], ["g then i f c d a v s", "go to a page"], ["g r", "switch repository"], ["n", "new: describe a change"], [": or ⌘K", "run a command"], ["⏎", "open selected"], ["esc", "close"], ["a/b/c", "answer a question"], ["letters on buttons", "run that action"],
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
