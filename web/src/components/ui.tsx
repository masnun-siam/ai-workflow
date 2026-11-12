import type { ComponentChildren } from "preact";
import type { Tone } from "../api/types";

export const Kbd = ({ children }: { children: ComponentChildren }) => <kbd>{children}</kbd>;
export const Tag = ({ tone, children }: { tone?: Tone | string; children: ComponentChildren }) => <span class={`tag ${tone ?? ""}`}>{children}</span>;
export const Empty = ({ children }: { children: ComponentChildren }) => <div class="empty">{children}</div>;

export function Pane({ label, children, wide }: { label: string; children: ComponentChildren; wide?: boolean }) {
  return (
    <section class="pane" style={wide ? { gridColumn: "1/-1" } : undefined} aria-label={label}>
      <h2 class="lb">{label}</h2>
      {children}
    </section>
  );
}

type BtnProps = {
  children: ComponentChildren; onClick?: () => void; k?: string; primary?: boolean; bad?: boolean; small?: boolean;
  disabled?: boolean; title?: string; type?: "button" | "submit";
};
export function Btn({ children, onClick, k, primary, bad, small, disabled, title, type = "button" }: BtnProps) {
  return (
    <button type={type} class={`btn${primary ? " pri" : ""}${bad ? " bad" : ""}${small ? " sm" : ""}`} onClick={onClick} disabled={disabled} title={title}>
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

export function Field({ label, children }: { label: string; children: ComponentChildren }) {
  return <label class="fld">{label}{children}</label>;
}
