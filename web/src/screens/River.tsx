import { useEffect, useRef } from "preact/hooks";
import { http } from "../api/http";
import { loadErrors, mutate, product, river, soloRepo } from "../state/data";
import { stages } from "../state/select";
import { detailOpen, sel, setSel } from "../state/ui";
import { prefs } from "../state/prefs";
import { useState } from "preact/hooks";
import { Header } from "../components/Header";
import { Btn, Empty, Pane } from "../components/ui";

/** Marks the wrapper `can-l` / `can-r` while the stages overflow on that side, so the CSS can show an edge fade. */
function useScrollCue(dep: unknown) {
  const wrap = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const w = wrap.current, el = w?.firstElementChild as HTMLElement | null;
    if (!w || !el) return;
    const upd = () => {
      w.classList.toggle("can-l", el.scrollLeft > 4);
      w.classList.toggle("can-r", el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
    };
    upd();
    el.addEventListener("scroll", upd, { passive: true });
    window.addEventListener("resize", upd);
    return () => { el.removeEventListener("scroll", upd); window.removeEventListener("resize", upd); };
  }, [dep]);
  return wrap;
}

/** Refresh from GitHub; the label says so while the request is out. */
function RefreshBtn({ body }: { body: Record<string, unknown> }) {
  const [busy, setBusy] = useState(false);
  const go = async () => { setBusy(true); try { await mutate(() => http.send("POST", "/api/refresh", body), "Refreshing from GitHub"); } finally { setBusy(false); } };
  return <Btn small disabled={busy} onClick={go}>{busy ? "Refreshing…" : "Refresh"}</Btn>;
}

export function River() {
  const s = sel.value;
  const st = stages.value;
  const err = loadErrors.value.river;
  // A repo with no product gets a River of its own; product chips would not change it.
  const solo = soloRepo.value;
  const scope = solo ?? product.value;
  const wrap = useScrollCue(river.value ? st : null);
  return (
    <>
      <Header title="River" products={!solo} scope={!solo}>
        <RefreshBtn body={solo ? { repo: solo } : { product: product.value }} />
      </Header>
      {err && <div class="banner bad" role="alert">{err}</div>}
      {river.value && river.value.stale.length > 0 && <div class="banner">Stale GitHub data: {river.value.stale.join(", ")}</div>}
      <Pane label={`river · ${scope ?? "no product"}`}>
        {!river.value ? <Empty>Loading…</Empty> : (
          <div class="river-wrap" ref={wrap}><div class="river">
            {st.map((stage, si) => (
              <div key={stage.id} class={`stage${stage.cards.some((c) => c.need) ? " hot" : ""}${si === s.stage && stage.cards.length > 0 ? " cur" : ""}`}>
                <div class="sh"><b>{stage.name}</b><span>{stage.skills}</span></div>
                {stage.cards.map((c, ci) => {
                  const selected = si === s.stage && ci === s.card;
                  return (
                    <button key={c.id} type="button" class={`card${c.need ? " need" : ""}${selected ? " sel" : ""}`} aria-current={selected}
                      onClick={() => { setSel({ stage: si, card: ci }); if (prefs.value.layout === "drawer") detailOpen.value = true; }}>
                      <span class="t">{c.title}</span>
                      <span class="m"><span class={`tag ${c.tone}`}>{c.tag}</span>{c.meta.trim().toLowerCase() === c.tag.trim().toLowerCase() ? "" : c.meta}</span>
                      {c.live && <span class="live" role="img" aria-label="live" />}
                    </button>
                  );
                })}
                {stage.cards.length === 0 && <span class="dim">Nothing here.</span>}
              </div>
            ))}
          </div></div>
        )}
      </Pane>
    </>
  );
}
