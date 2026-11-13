import { useEffect, useRef, useState } from "preact/hooks";
import type { RegistryStep } from "../api/extra";
import { registry } from "../state/data";
import { goScreen, nav, SCREENS, type ScreenId } from "../state/route";
import { confirmReq, helpOpen, holdToast, openCreate, paletteOpen, releaseToast, startReq, toast, toastMsg } from "../state/ui";
import { clamp } from "../state/ui";
import { HINTS, hintsFor } from "../state/keymap";
import { Btn, useFocusTrap, useLayer } from "./ui";

const RUNS_IN: Record<string, string> = { docs: "in a docs repo", issue: "on an issue", repo: "in a repo", none: "no repo needed" };

export function matchSteps(steps: RegistryStep[], q: string): RegistryStep[] {
  const s = q.trim().toLowerCase();
  return steps.filter((x) => `${x.id} ${x.skill} ${x.source}`.toLowerCase().includes(s));
}

type PalRow = { k: "skill"; s: RegistryStep } | { k: "go"; id: ScreenId; label: string; key: string } | { k: "free" } | { k: "describe" };

/** Page-jump entries whose name matches the query (all of them for an empty query), with their number key. */
export function matchPages(q: string): { id: ScreenId; label: string; key: string }[] {
  const s = q.trim().toLowerCase();
  return SCREENS.map(([id, label], n) => ({ id, label, key: String((n + 1) % 10) })).filter((p) => !s || `${p.label} ${p.id}`.toLowerCase().includes(s));
}

export function Palette() {
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const ref = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);
  useLayer(() => (paletteOpen.value = false));
  useEffect(() => ref.current?.focus(), []);
  useEffect(() => { document.querySelector("#pal-list .sel")?.scrollIntoView?.({ block: "nearest" }); }, [i]);
  const skills = matchSteps(registry.value, q);
  const rows: PalRow[] = [...skills.map((s): PalRow => ({ k: "skill", s })), ...matchPages(q).map((p): PalRow => ({ k: "go", ...p })), ...(q.trim() ? [{ k: "free" } as PalRow] : []), { k: "describe" }];
  const total = rows.length;
  const pick = (n: number) => {
    const row = rows[n];
    if (!row) return;
    if (row.k === "skill" && !row.s.available) { toast(row.s.reason ?? `${row.s.id} is not available`, "warn"); return; }
    paletteOpen.value = false;
    if (row.k === "skill") startReq.value = { step: row.s };
    else if (row.k === "go") goScreen(row.id);
    else if (row.k === "free") startReq.value = { step: null, args: q.trim() };
    else openCreate(q.trim() || undefined);
  };
  const props = (n: number) => ({ id: `pal-${n}`, type: "button" as const, role: "option" as const, "aria-selected": n === i, onMouseMove: () => n !== i && setI(n), onClick: () => pick(n) });
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) paletteOpen.value = false; }}>
      <div class="dlg" ref={box} role="dialog" aria-modal="true" aria-label="Command palette">
        <input ref={ref} class="pal-q" role="combobox" aria-activedescendant={total ? `pal-${i}` : undefined} aria-expanded={total > 0} aria-controls="pal-list" placeholder="Search skills and pages, or type a prompt to run as free text…" aria-label="Search skills and pages" value={q}
          onInput={(e) => { setQ((e.target as HTMLInputElement).value); setI(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { setI(clamp(i + 1, 0, total - 1)); e.preventDefault(); }
            else if (e.key === "ArrowUp") { setI(clamp(i - 1, 0, total - 1)); e.preventDefault(); }
            else if (e.key === "Enter") { pick(i); e.preventDefault(); }
          }} />
        <div id="pal-list" role="listbox" aria-label="Skills and pages">
          {rows.map((row, n) => {
            const on = n === i;
            if (row.k === "skill") {
              const s = row.s;
              return (
                <button key={`s-${s.id}`} {...props(n)} aria-disabled={!s.available} class={`pi${on ? " sel" : ""}${s.available ? "" : " off"}`} title={s.reason}>
                  <span class="c-w">/</span>{s.source === "blubird" ? "blubird:" : ""}{s.id}<span class="r">{s.available ? RUNS_IN[s.runs_in] ?? s.runs_in : (s.reason ?? "unavailable")}</span>
                </button>
              );
            }
            if (row.k === "go") return <button key={`g-${row.id}`} {...props(n)} class={`pi${on ? " sel" : ""}`}><span class="c-w">→</span>Go to {row.label}<span class="r"><kbd>{row.key}</kbd></span></button>;
            if (row.k === "free") return <button key="free" {...props(n)} class={`pi${on ? " sel" : ""}`}><span class="c-w">›</span>Run as free text: <b>{q.trim()}</b><span class="r">{skills.length ? "" : "no skill matches"}</span></button>;
            return <button key="describe" {...props(n)} class={`pi${on ? " sel" : ""}`}><span class="c-w">+</span>Describe a feature or a fix{q.trim() ? <>: <b>{q.trim()}</b></> : null}<span class="r"><kbd>n</kbd></span></button>;
          })}
          {!skills.length && !q.trim() && <div class="empty">No skills loaded yet.</div>}
        </div>
        <div class="dlg-foot"><span><kbd>↑↓</kbd>move</span><span><kbd>⏎</kbd>choose</span><span><kbd>esc</kbd>close</span></div>
      </div>
    </div>
  );
}

export function ConfirmDialog() {
  const c = confirmReq.value!;
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);
  useLayer(() => c.resolve(false));
  // a destructive confirm starts on "No", so a stray Enter or Space cannot confirm it
  useEffect(() => box.current?.querySelector<HTMLElement>(c.danger ? ".acts button:last-child" : ".acts button")?.focus(), []);
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) c.resolve(false); }}>
      <div class="dlg form narrow" ref={box} role="alertdialog" aria-modal="true" aria-labelledby="confirm-t"
        onKeyDown={(e) => { if (e.key === "y") c.resolve(true); else if (e.key === "n") c.resolve(false); }}>
        <span id="confirm-t">{c.text}</span>
        <div class="acts"><button type="button" class="btn pri" onClick={() => c.resolve(true)}><kbd>y</kbd>Yes</button><Btn k="n" onClick={() => c.resolve(false)}>No</Btn></div>
      </div>
    </div>
  );
}

const GLOBAL: [string, string][] = [["1-9, 0", "go to a page"], ["g then i f c d a v s", "go to a page"], ["g r", "switch repository"], ["n", "new: describe a change"], [": or ⌘K", "run a command"], ["⏎", "open selected"], ["esc", "close"], ["a/b/c", "answer a question"], ["letters on buttons", "run that action"],
  [".", "mode: system / dark / light"], ["s", "look: classic / console / river"], ["L", "layout: drawer / split"], ["?", "this help"]];
export function Help() {
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box, true);
  useLayer(() => (helpOpen.value = false));
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) helpOpen.value = false; }}>
      <div class="dlg" ref={box} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="help-h">
        <div class="dlg-top"><h2 id="help-h" class="dlg-h">Keyboard shortcuts</h2><Btn k="esc" small onClick={() => (helpOpen.value = false)}>close</Btn></div>
        <div class="help">{GLOBAL.map(([k, d]) => <><kbd>{k}</kbd><span>{d}</span></>)}
          <h3 class="gh help-sep">On each screen</h3>
          {Object.keys(HINTS).filter((s) => s !== "prd").map((s) => [s, hintsFor(s, true)] as const).map(([s, hs]) => <><b class="help-scr">{s}</b><span>{hs.map(([k, d]) => `${k} ${d}`).join(" · ")}</span></>)}</div>
      </div>
    </div>
  );
}

/** The live region is always mounted, so a screen reader hears each new toast. Hover or focus pauses the timer. */
export function Toast() {
  const t = toastMsg.value;
  return (
    <div class="toast-live" aria-live="polite" aria-atomic="true" onMouseEnter={holdToast} onMouseLeave={releaseToast} onFocusIn={holdToast} onFocusOut={releaseToast}>
      {t && (
        <div class={`toast ${t.level}`} role={t.level === "error" ? "alert" : undefined}>
          {t.msg}
          {t.path && <button type="button" onClick={() => { nav(t.path!); toastMsg.value = null; }}>Open</button>}
          <button type="button" aria-label="Dismiss" onClick={() => (toastMsg.value = null)}>×</button>
        </div>
      )}
    </div>
  );
}
