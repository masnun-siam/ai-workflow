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

export function Settings() {
  return (
    <>
      <Header title="settings" />
      {loadErrors.value.settings && <div class="banner bad" role="alert">{loadErrors.value.settings}</div>}
      <div class="grid2">
        <Appearance />
        <BlubirdPane />
        <ProductsPane />
        <ReleaseNotePane />
        <AccountsPane />
        <NotificationsPane />
        <ReviewPane />
        <AwayPane />
        <JevVaultPane />
        <ServerPane />
      </div>
    </>
  );
}
