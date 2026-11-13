import type { ComponentChildren, RefObject } from "preact";
import { useEffect, useState } from "preact/hooks";
import type { Tone } from "../api/types";

export const Kbd = ({ children }: { children: ComponentChildren }) => <kbd>{children}</kbd>;
export const Tag = ({ tone, children }: { tone?: Tone | string; children: ComponentChildren }) => <span class={`tag ${tone ?? ""}`}>{children}</span>;
export const Empty = ({ children }: { children: ComponentChildren }) => <div class="empty">{children}</div>;

export function Pane({ label, children, wide, id }: { label: string; children: ComponentChildren; wide?: boolean; id?: string }) {
  return (
    <section class="pane" id={id} style={wide ? { gridColumn: "1/-1" } : undefined} aria-label={label}>
      <h2 class="lb">{label}</h2>
      {children}
    </section>
  );
}

type BtnProps = {
  children: ComponentChildren; onClick?: () => unknown; k?: string; primary?: boolean; bad?: boolean; small?: boolean;
  disabled?: boolean; title?: string; type?: "button" | "submit"; label?: string;
};
/** A button. When onClick returns a promise the button is busy (disabled) until it settles, so a slow call cannot be sent twice. */
export function Btn({ children, onClick, k, primary, bad, small, disabled, title, type = "button", label }: BtnProps) {
  const [busy, setBusy] = useState(false);
  const click = () => {
    const r = onClick?.();
    if (r instanceof Promise) { setBusy(true); void r.finally(() => setBusy(false)); }
  };
  return (
    <button type={type} class={`btn${primary ? " pri" : ""}${bad ? " bad" : ""}${small ? " sm" : ""}`} onClick={onClick ? click : undefined}
      disabled={disabled || busy} aria-busy={busy || undefined} aria-label={label} title={title}>
      {k && <kbd>{k}</kbd>}
      {children}
    </button>
  );
}

export function KV({ rows }: { rows: [string, ComponentChildren][] }) {
  return (
    <div class="kv">
      {rows.map(([k, v]) => (
        <>
          <span>{k}</span>
          <span>{v}</span>
        </>
      ))}
    </div>
  );
}

export function Meter({ pct, label }: { pct: number; label: string }) {
  const v = Math.max(0, Math.min(100, Math.round(pct)));
  return (
    <div class="meter" role="meter" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <i style={{ width: `${v}%` }} />
    </div>
  );
}

export function Chips<T extends string>({ value, options, onPick, label }: { value: T; options: [T, string][]; onPick: (v: T) => void; label: string }) {
  return (
    <div class="chips" role="group" aria-label={label}>
      {options.map(([v, l]) => (
        <button type="button" class={`chip${v === value ? " on" : ""}`} aria-pressed={v === value} onClick={() => onPick(v)}>{l}</button>
      ))}
    </div>
  );
}

export function Field({ label, children, hint, error }: { label: string; children: ComponentChildren; hint?: string; error?: string | null }) {
  return <label class="fld">{label}{children}{error ? <small class="c-b" role="alert">{error}</small> : hint && <small class="dim">{hint}</small>}</label>;
}

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/** Keeps Tab inside a dialog while it is open and gives focus back to where it was when it closes. */
export function useFocusTrap(ref: RefObject<HTMLElement | null>, focusSelf = false): void {
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const el = ref.current;
    if (el && !el.contains(document.activeElement)) ((focusSelf ? null : el.querySelector<HTMLElement>(FOCUSABLE)) ?? el).focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || !el) return;
      const list = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((x) => x.offsetParent !== null);
      if (!list.length) return;
      const first = list[0]!, last = list[list.length - 1]!;
      if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); }
      else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
    };
    el?.addEventListener("keydown", onKey);
    return () => { el?.removeEventListener("keydown", onKey); if (prev && document.contains(prev)) prev.focus(); };
  }, []);
}
