import { loadErrors } from "../state/data";
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

export function Settings() {
  return (
    <>
      <Header title="settings" />
      <nav class="chips jump" aria-label="Settings sections">
        {JUMP.map(([id, name]) => <a key={id} class="chip" href={`#${id}`} onClick={(e) => { e.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }); }}>{name}</a>)}
      </nav>
      {loadErrors.value.settings && <div class="banner bad" role="alert">{loadErrors.value.settings}</div>}
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
    </>
  );
}
