import { useState } from "preact/hooks";
import { http } from "../../api/http";
import type { ReviewConfig } from "../../api/types";
import { mutate, reviewCfg } from "../../state/data";
import { Btn, Field, Pane } from "../../components/ui";
import { csv } from "./common";

export function ReviewPane() {
  const c = reviewCfg.value;
  const [d, setD] = useState<{ max: number; lenses: string; defs: string } | null>(null);
  if (!c) return <Pane label="peer review"><span class="dim">Loading…</span></Pane>;
  const v = d ?? { max: c.max_rounds, lenses: Object.entries(c.lenses).map(([k, t]) => `${k}: ${t}`).join("\n"), defs: c.default_lenses.join(", ") };
  const save = async () => {
    const lenses: Record<string, string> = {};
    for (const line of v.lenses.split("\n")) { const i = line.indexOf(":"); if (i > 0) lenses[line.slice(0, i).trim()] = line.slice(i + 1).trim(); }
    const r = await mutate(() => http.send<ReviewConfig>("PUT", "/api/settings/review", { max_rounds: v.max, default_lenses: csv(v.defs), lenses }), "Saved");
    if (r) { reviewCfg.value = r; setD(null); }
  };
  return (
    <Pane label="peer review">
      <div class="det">
        <div class="fields">
          <Field label="Max rounds"><input type="number" min={1} max={10} value={v.max} onInput={(e) => setD({ ...v, max: Number((e.target as HTMLInputElement).value) })} /></Field>
          <Field label="Default lenses (comma separated)"><input value={v.defs} onInput={(e) => setD({ ...v, defs: (e.target as HTMLInputElement).value })} /></Field>
        </div>
        <Field label="Lenses, one per line as name: instructions"><textarea rows={5} value={v.lenses} onInput={(e) => setD({ ...v, lenses: (e.target as HTMLTextAreaElement).value })} /></Field>
        <div class="acts"><Btn primary disabled={!d} onClick={() => void save()}>Save</Btn>
          <Btn disabled={!c.overridden} onClick={async () => { const r = await mutate(() => http.send<ReviewConfig>("PUT", "/api/settings/review", { reset: true }), "Reset to shipped lenses"); if (r) { reviewCfg.value = r; setD(null); } }}>Reset to shipped</Btn></div>
      </div>
    </Pane>
  );
}
