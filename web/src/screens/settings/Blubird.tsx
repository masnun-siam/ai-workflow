import { http } from "../../api/http";
import type { Blubird as B } from "../../api/types";
import { blubird, mutate, status } from "../../state/data";
import { Btn, KV, Pane } from "../../components/ui";
import { askConfirm } from "../../state/ui";

const currentBlubird = (): B | null => blubird.value ?? status.value?.blubird ?? null;

/** Update or reinstall blubird, for the pane buttons and the `u`/`i` keys alike: off while busy (and, for update, while not installed); a reinstall asks first. */
export async function blubirdAction(what: "install" | "update"): Promise<void> {
  const b = currentBlubird();
  if (!b || b.busy || (what === "update" && !b.installed)) return;
  if (what === "install" && b.installed && !(await askConfirm("Reinstall blubird? Running sessions keep the old copy."))) return;
  await runBlubird(what);
}

export function BlubirdPane() {
  const b: B | null = currentBlubird();
  if (!b) return <Pane label="blubird"><span class="dim">Loading…</span></Pane>;
  return (
    <Pane label="blubird" id="set-blubird">
      <div class="det">
        <KV rows={[
          ["installed", b.installed ? <span class="c-o">{b.version}</span> : <span class="c-b">not installed</span>],
          ["latest", b.latest ? `${b.latest}${b.update_available ? " · update available" : " · up to date"}` : "unknown"],
          ["marketplace", <span class="mono">{b.marketplace}</span>], ["path", <span class="mono">{b.install_path}</span>],
          ["skills", b.skills.length], ["hooks", b.hooks.join(" · ") || "none"],
        ]} />
        {b.busy && <span class="c-q" role="status">{b.busy}…</span>}
        {b.error && <div class="banner bad" role="alert">{b.error}</div>}
        <div class="acts">
          <Btn k="u" disabled={!!b.busy || !b.installed} onClick={() => blubirdAction("update")}>Check / update</Btn>
          <Btn k="i" primary={!b.installed} disabled={!!b.busy} onClick={() => blubirdAction("install")}>{b.installed ? "Reinstall" : "Install"}</Btn>
        </div>
      </div>
    </Pane>
  );
}

export function runBlubird(what: "install" | "update"): Promise<unknown> {
  return mutate(() => http.send("POST", `/api/blubird/${what}`, {}), what === "install" ? "Installing blubird" : "Checking blubird", ["blubird", "status"]);
}
