import { inbox, loadErrors, product } from "../state/data";
import { GROUPS, inboxItems } from "../state/select";
import { detailOpen, sel, setSel } from "../state/ui";
import { prefs } from "../state/prefs";
import { ago, shortRepo } from "../state/format";
import { Header } from "../components/Header";
import { Empty, Pane } from "../components/ui";

export function Inbox() {
  const items = inboxItems.value;
  const cur = sel.value.inbox;
  const err = loadErrors.value.inbox;
  return (
    <>
      <Header title="inbox" products />
      {err && <div class="banner bad" role="alert">{err}</div>}
      {inbox.value && inbox.value.stale.length > 0 && <div class="banner">Stale GitHub data: {inbox.value.stale.join(", ")}</div>}
      <Pane label={`inbox · ${inbox.value?.count ?? 0} need you${product.value ? "" : ""}`}>
        <div class="rows">
          {GROUPS.map(([g, name]) => {
            const rows = items.map((it, i) => ({ it, i })).filter((x) => x.it.group === g);
            if (!rows.length) return null;
            return (
              <div key={g} role="group" aria-label={name}>
                <div class="gh">{name}</div>
                {rows.map(({ it, i }) => (
                  <button key={it.key} type="button" class={`row${i === cur ? " sel" : ""}`} aria-current={i === cur}
                    onClick={() => { setSel({ inbox: i }); if (prefs.value.layout === "drawer") detailOpen.value = true; }}>
                    <span class={`tag ${g === "wait" ? "" : "c-w"}`}>{it.kind}</span>
                    <span class="t">{it.title}</span>
                    <span class="w">{shortRepo(it.repo)} {ago(it.at)}</span>
                  </button>
                ))}
              </div>
            );
          })}
          {inbox.value && items.length === 0 && <Empty>Nothing needs you.</Empty>}
          {!inbox.value && <Empty>Loading…</Empty>}
        </div>
      </Pane>
    </>
  );
}
