import { inbox, inboxCached, loadErrors } from "../state/data";
import { COLLAPSE_AFTER, COLLAPSIBLE, GROUPS, KIND_GROUPED, inboxAll, inboxExpanded, inboxItems, inboxQuery, runningCount, toggleExpanded } from "../state/select";
import { displayTitle } from "../state/inboxView";
import { detailOpen, sel, setSel } from "../state/ui";
import { prefs } from "../state/prefs";
import { ago, shortRepo } from "../state/format";
import { Header } from "../components/Header";
import { Btn, Empty, Pane } from "../components/ui";
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
      {inboxCached.value && <div class="banner" role="status">Showing the last inbox this browser saw while GitHub refreshes.</div>}
      <Pane label={inbox.value ? `inbox · ${inbox.value.count} need you` : "inbox"}>
        <div class="filters"><input type="search" placeholder="Filter by title, kind or repo" aria-label="Filter the inbox" value={inboxQuery.value} onInput={(e) => (inboxQuery.value = (e.target as HTMLInputElement).value)} /></div>
        <div class="rows">
          {GROUPS.map(([g, name]) => {
            const rows = items.map((it, i) => ({ it, i })).filter((x) => x.it.group === g);
            if (!rows.length) return null;
            const kinds = KIND_GROUPED.has(g) ? [...new Set(rows.map((x) => x.it.kind))] : [""];
            return (
              <div key={g} role="group" aria-label={name}>
                <div class="gh">{name}</div>
                {kinds.map((k) => {
                  const part = k ? rows.filter((x) => x.it.kind === k) : rows;
                  const total = k ? inboxAll.value.filter((x) => x.group === g && x.kind === k).length : part.length;
                  const open = inboxExpanded.value.has(k);
                  return (
                    <div key={k} role={k ? "group" : undefined} aria-label={k ? `${name}: ${k}` : undefined}>
                      {k && <div class="gh sub">{k} · {total}</div>}
                      {part.map(({ it, i }) => (
                        <button key={it.key} type="button" class={`row${i === cur ? " sel" : ""}`} aria-current={i === cur}
                          onClick={() => { setSel({ inbox: i }); if (prefs.value.layout === "drawer") detailOpen.value = true; }}>
                          <span class={`tag ${g === "wait" ? "" : "c-w"}`}><span aria-hidden="true">{g === "wait" ? "◷ " : "▲ "}</span><span class="sr">{g === "wait" ? "Waiting: " : "Needs you: "}</span>{it.kind}</span>
                          <span class="t">{displayTitle(it)}</span>
                          <span class="w">{shortRepo(it.repo)} {ago(it.at)}</span>
                        </button>
                      ))}
                      {k && total > COLLAPSE_AFTER && inboxQuery.value.trim() === "" && COLLAPSIBLE.has(k) && (
                        <div class="acts"><Btn small onClick={() => toggleExpanded(k)}>{open ? `Show first ${COLLAPSE_AFTER}` : `Show all ${total}`}</Btn></div>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })}
          {inbox.value && items.length === 0 && inboxQuery.value.trim() !== "" && <Empty>No inbox row matches.</Empty>}
          {inbox.value && items.length === 0 && inboxQuery.value.trim() === "" && <Empty>All clear. New questions, approvals and failures show up here. <a href="#/activity">See what is running</a></Empty>}
          {!inbox.value && <Empty>Loading from GitHub…</Empty>}
        </div>
      </Pane>
    </>
  );
}
