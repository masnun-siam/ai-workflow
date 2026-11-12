import { http } from "../api/http";
import { loadErrors, mutate, product, river } from "../state/data";
import { stages } from "../state/select";
import { detailOpen, sel, setSel } from "../state/ui";
import { prefs } from "../state/prefs";
import { Header } from "../components/Header";
import { Btn, Empty, Pane } from "../components/ui";

export function River() {
  const s = sel.value;
  const st = stages.value;
  const err = loadErrors.value.river;
  return (
    <>
      <Header title="river" products>
        <Btn small onClick={() => void mutate(() => http.send("POST", "/api/refresh", { product: product.value }), "Refreshing from GitHub")}>Refresh</Btn>
      </Header>
      {err && <div class="banner bad" role="alert">{err}</div>}
      {river.value && river.value.stale.length > 0 && <div class="banner">Stale GitHub data: {river.value.stale.join(", ")}</div>}
      <Pane label={`river · ${product.value ?? "no product"}`}>
        {!river.value ? <Empty>Loading…</Empty> : (
          <div class="river">
            {st.map((stage, si) => (
              <div key={stage.id} class={`stage${stage.cards.some((c) => c.need) ? " hot" : ""}${si === s.stage ? " cur" : ""}`}>
                <div class="sh"><b>{stage.name}</b><span>{stage.skills}</span></div>
                {stage.cards.map((c, ci) => {
                  const selected = si === s.stage && ci === s.card;
                  return (
                    <button key={c.id} type="button" class={`card${c.need ? " need" : ""}${selected ? " sel" : ""}`} aria-current={selected}
                      onClick={() => { setSel({ stage: si, card: ci }); if (prefs.value.layout === "drawer") detailOpen.value = true; }}>
                      <span class="t">{c.title}</span>
                      <span class="m"><span class={`tag ${c.tone}`}>{c.tag}</span>{c.meta}</span>
                      {c.live && <span class="live" role="img" aria-label="live" />}
                    </button>
                  );
                })}
                {stage.cards.length === 0 && <span class="dim">Nothing here.</span>}
              </div>
            ))}
          </div>
        )}
      </Pane>
    </>
  );
}
