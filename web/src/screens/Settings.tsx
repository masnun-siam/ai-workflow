import { useEffect } from "preact/hooks";
import { loadErrors, loadMany, settings } from "../state/data";
import { route, setParam } from "../state/route";
import { Btn } from "../components/ui";
import { Header } from "../components/Header";
import { Appearance } from "./settings/Appearance";
import { BlubirdPane } from "./settings/Blubird";
import { ProductsPane } from "./settings/Products";
import { ReleaseNotePane } from "./settings/ReleaseNote";
import { AccountsPane } from "./settings/Accounts";
import { NotificationsPane } from "./settings/Notifications";
import { ReviewPane } from "./settings/Review";
import { AwayPane } from "./settings/Away";
import { JevVaultPane, ServerPane } from "./settings/Integrations";

const JUMP: [string, string][] = [["set-appearance", "Appearance"], ["set-blubird", "blubird"], ["set-away", "Away"], ["set-jev", "jev and vault"], ["set-products", "Products and repos"],
  ["set-accounts", "Accounts"], ["set-notify", "Notifications"], ["set-release", "Release note"], ["set-review", "Peer review"], ["set-server", "Server and grind"]];

const scrollTo = (id: string, smooth = false) => document.getElementById(id)?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });

export function Settings() {
  const pane = route.value.query.pane;
  useEffect(() => { if (pane) scrollTo(`set-${pane}`); }, [pane]);
  const failed = ["settings", "notify", "review"].map((k) => loadErrors.value[k]).filter(Boolean);
  const jump = (e: Event, id: string) => {
    e.preventDefault();
    const name = id.slice(4);
    if (pane === name) scrollTo(id, true); else setParam("pane", name);
  };
  return (
    <>
      <Header title="Settings" />
      <nav class="chips jump" aria-label="Settings sections">
        {JUMP.map(([id, name]) => <a key={id} class="chip" href={`#${id}`} aria-current={pane === id.slice(4) ? "true" : undefined} onClick={(e) => jump(e, id)}>{name}</a>)}
      </nav>
      {failed.length > 0 && <div class="banner bad" role="alert">{failed[0]} <Btn small onClick={() => loadMany(["settings", "notify", "review"])}>Retry</Btn></div>}
      {!settings.value && failed.length > 0 ? null : (
        <div class="grid2">
          <Appearance />
          <BlubirdPane />
          <AwayPane />
          <JevVaultPane />
          <ProductsPane />
          <AccountsPane />
          <NotificationsPane />
          <ReleaseNotePane />
          <ReviewPane />
          <ServerPane />
        </div>
      )}
    </>
  );
}
