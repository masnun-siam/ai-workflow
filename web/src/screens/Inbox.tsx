import { inbox, loadErrors } from "../state/data";
import { GROUPS, inboxItems, runningCount } from "../state/select";
import { detailOpen, sel, setSel } from "../state/ui";
import { prefs } from "../state/prefs";
import { ago, shortRepo } from "../state/format";
import { Header } from "../components/Header";
import { Empty, Pane } from "../components/ui";
import { Questions } from "../components/Questions";
import { AwaySummary } from "../components/AwaySummary";

export function Inbox() {
  const items = inboxItems.value;
  const cur = sel.value.inbox;
  const err = loadErrors.value.inbox;
  return (
    <>
      <Header title="Inbox" scope sub={inbox.value ? <>{inbox.value.count ? `${inbox.value.count} ${inbox.value.count === 1 ? "thing needs" : "things need"} you across your repos` : "All clear"}{runningCount.value ? <> · <a href="#/activity">{runningCount.value} sessions working</a></> : null}</> : undefined} />
      {err && <div class="banner bad" role="alert">{err}</div>}
      <AwaySummary />
      {prefs.value.layout === "drawer" && <Questions />}
      {inbox.value && inbox.value.stale.length > 0 && <div class="banner">Stale GitHub data: {inbox.value.stale.join(", ")}</div>}
      <Pane label={inbox.value ? `inbox · ${inbox.value.count} need you` : "inbox"}>
        <div class="rows">
          {GROUPS.map(([g, name]) => {
            const rows = items.map((it, i) => ({ it, i })).filter((x) => x.it.group === g);
            if (!rows.length) return null;
            return (
              <div key={g} role="group" aria-label={name}>
                <div class="gh">{name}</div>
                {rows.map(({ it, i }) => (
                  <button key={it.key} type="button" class={`row${i === cur ? " sel" : ""}`} aria-current={i === cur || undefined}
                    onClick={() => { setSel({ inbox: i }); if (prefs.value.layout === "drawer") detailOpen.value = true; }}>
                    <span class={`tag ${g === "wait" ? "" : "c-w"}`}>{it.kind}</span>
                    <span class="t">{it.title}</span>
                    <span class="w">{shortRepo(it.repo)} {ago(it.at)}</span>
                  </button>
                ))}
              </div>
            );
          })}
          {inbox.value && items.length === 0 && <Empty>All clear. New questions, approvals and failures show up here. <a href="#/activity">See what is running</a></Empty>}
          {!inbox.value && <Empty>Loading from GitHub…</Empty>}
        </div>
      </Pane>
    </>
  );
}
