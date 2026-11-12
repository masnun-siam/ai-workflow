import { loadErrors, ops } from "../state/data";
import { opsRows } from "../state/select";
import { detailOpen, sel, setSel } from "../state/ui";
import { prefs } from "../state/prefs";
import { Header } from "../components/Header";
import { Empty, Pane } from "../components/ui";

export function Ops() {
  return (
    <>
      <Header title="Ops" products />
      {loadErrors.value.ops && <div class="banner bad" role="alert">{loadErrors.value.ops}</div>}
      <Pane label="ops">
        <div class="rows">
          {opsRows.value.map((o, i) => (
            <button key={o.step} type="button" class={`row${i === sel.value.ops ? " sel" : ""}`} aria-current={i === sel.value.ops} style={{ gridTemplateColumns: "minmax(0,1.1fr) 90px minmax(0,1.4fr)" }}
              onClick={() => { setSel({ ops: i }); if (prefs.value.layout === "drawer") detailOpen.value = true; }}>
              <span class="t mono">{o.label}</span><span class="w">{o.scope}</span><span class="t mu">{o.summary}</span>
            </button>
          ))}
          {ops.value && opsRows.value.length === 0 && <Empty>No ops for this product.</Empty>}
          {!ops.value && <Empty>Loading…</Empty>}
        </div>
      </Pane>
    </>
  );
}
