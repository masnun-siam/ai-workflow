/** The one dropdown: a field-styled trigger and the same popover list the repo pickers use.
 *  Every picker in the app (Select, RepoField, RepoScope) renders DdTrigger, so they look alike. */
import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { Popover } from "./Shell";

export const Chevron = () => (
  <svg class="dd-chev" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
);

export function DdTrigger({ open, onClick, label, children, aside, compact }: {
  open: boolean; onClick: () => void; label: string; children: ComponentChildren; aside?: ComponentChildren; compact?: boolean;
}) {
  return (
    <button type="button" class={`dd${compact ? " compact" : ""}${open ? " open" : ""}`} aria-haspopup="listbox" aria-expanded={open} aria-label={label} onClick={onClick}>
      <span class="dd-v">{children}</span>{aside && <span class="dd-aside">{aside}</span>}<Chevron />
    </button>
  );
}

export type Opt<T extends string> = { value: T; label: string; hint?: string };

/** A select. `options` are [value, label] pairs or objects; a filter box shows above 8 options. */
export function Select<T extends string>({ value, onChange, options, label, compact }: {
  value: T; onChange: (v: T) => void; options: ([T, string] | Opt<T>)[]; label: string; compact?: boolean;
}) {
  const opts: Opt<T>[] = options.map((o) => (Array.isArray(o) ? { value: o[0], label: o[1] } : o));
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const list = useRef<HTMLDivElement>(null);
  const filter = opts.length > 8;
  const s = q.trim().toLowerCase();
  const shown = opts.filter((o) => !s || `${o.label} ${o.hint ?? ""}`.toLowerCase().includes(s));
  const cur = opts.find((o) => o.value === value);
  useEffect(() => {
    if (!open) return;
    setQ("");
    setI(Math.max(0, opts.findIndex((o) => o.value === value)));
    setTimeout(() => (list.current?.querySelector<HTMLElement>(filter ? "input" : ".pi.sel") ?? list.current)?.focus(), 0);
  }, [open]);
  useEffect(() => { list.current?.querySelector(".pi.sel")?.scrollIntoView?.({ block: "nearest" }); }, [i, open]);
  const pick = (o: Opt<T> | undefined) => { if (!o) return; setOpen(false); if (o.value !== value) onChange(o.value); };
  const keys = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown") { setI(Math.min(i + 1, shown.length - 1)); e.preventDefault(); }
    else if (e.key === "ArrowUp") { setI(Math.max(i - 1, 0)); e.preventDefault(); }
    else if (e.key === "Enter" || (e.key === " " && !filter)) { pick(shown[i]); e.preventDefault(); }
    else if (e.key === "Tab") setOpen(false);
  };
  return (
    <Popover open={open} setOpen={setOpen} fit trigger={
      <DdTrigger open={open} compact={compact} label={`${label}: ${cur?.label ?? "none"}`} onClick={() => setOpen(!open)}>{cur?.label ?? <span class="dim">Pick…</span>}</DdTrigger>
    }>
      <div class="rp" ref={list} role="listbox" aria-label={label} tabIndex={-1} onKeyDown={keys}>
        {filter && <input class="pal-q" placeholder={`Find (${opts.length})…`} aria-label={`Filter ${label}`} value={q} onInput={(e) => { setQ((e.target as HTMLInputElement).value); setI(0); }} />}
        <div class="rp-list">
          {shown.map((o, n) => (
            <button key={o.value} type="button" role="option" aria-selected={o.value === value} tabIndex={-1} class={`pi${n === i ? " sel" : ""}`}
              onMouseMove={() => n !== i && setI(n)} onClick={() => pick(o)}>
              <span class="grow">{o.label}</span>{o.hint && <span class="dim">{o.hint}</span>}{o.value === value && <span class="r">✓</span>}
            </button>
          ))}
          {!shown.length && <div class="empty">No match.</div>}
        </div>
      </div>
    </Popover>
  );
}
