import { useState } from "preact/hooks";
import { http } from "../../api/http";
import type { ReviewConfig } from "../../api/types";
import { mutate, reviewCfg } from "../../state/data";
import { askConfirm } from "../../state/ui";
import { Btn, Field, Pane } from "../../components/ui";
import { csv, intError, val } from "./common";

/** Why the lenses text cannot be saved: every non-blank line must read `name: instructions`. */
export function lensProblem(text: string): string | null {
  const bad = text.split("\n").map((l, i) => ({ l, n: i + 1 })).filter(({ l }) => l.trim() && l.indexOf(":") < 1).map((x) => x.n);
  return bad.length ? `Line ${bad.join(", ")} needs the form name: instructions` : null;
}

export function ReviewPane() {
  const c = reviewCfg.value;
  const [d, setD] = useState<{ max: string; lenses: string; defs: string } | null>(null);
  if (!c) return <Pane label="peer review"><span class="dim">Loading…</span></Pane>;
  const v = d ?? { max: String(c.max_rounds), lenses: Object.entries(c.lenses).map(([k, t]) => `${k}: ${t}`).join("\n"), defs: c.default_lenses.join(", ") };
  const maxErr = intError(v.max, 1, 20);
  const lensErr = lensProblem(v.lenses);
  const save = async () => {
    const lenses: Record<string, string> = {};
    for (const line of v.lenses.split("\n")) { const i = line.indexOf(":"); if (i > 0) lenses[line.slice(0, i).trim()] = line.slice(i + 1).trim(); }
    const r = await mutate(() => http.send<ReviewConfig>("PUT", "/api/settings/review", { max_rounds: Number(v.max), default_lenses: csv(v.defs), lenses }), "Saved");
    if (r) { reviewCfg.value = r; setD(null); }
  };
  return (
    <Pane label="peer review" id="set-review">
      <div class="det">
        <div class="fields">
          <Field label="Max rounds" error={d ? maxErr : null}><input type="number" min={1} max={20} value={v.max} aria-invalid={!!d && !!maxErr} onInput={(e) => setD({ ...v, max: val(e) })} /></Field>
          <Field label="Default lenses (comma separated)"><input value={v.defs} onInput={(e) => setD({ ...v, defs: (e.target as HTMLInputElement).value })} /></Field>
        </div>
        <Field label="Lenses, one per line as name: instructions" error={lensErr}><textarea rows={5} value={v.lenses} aria-invalid={!!lensErr} onInput={(e) => setD({ ...v, lenses: (e.target as HTMLTextAreaElement).value })} /></Field>
        <div class="acts"><Btn primary disabled={!d || !!maxErr || !!lensErr} onClick={() => save()}>Save</Btn>{d && <Btn onClick={() => setD(null)}>Discard</Btn>}
          <Btn disabled={!c.overridden} title={c.overridden ? undefined : "Already the shipped lenses"} onClick={async () => { if (!(await askConfirm("Replace your lenses with the shipped ones?", true))) return; const r = await mutate(() => http.send<ReviewConfig>("PUT", "/api/settings/review", { reset: true }), "Reset to shipped lenses"); if (r) { reviewCfg.value = r; setD(null); } }}>Reset to shipped</Btn></div>
      </div>
    </Pane>
  );
}
