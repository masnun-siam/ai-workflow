import { useState } from "preact/hooks";
import { http } from "../../api/http";
import type { Settings, VaultFolder } from "../../api/types";
import { mutate, settings } from "../../state/data";
import { Btn, Field, Pane } from "../../components/ui";
import { csv, saveSettings } from "./common";

export function JevVaultPane() {
  const s = settings.value;
  const [dir, setDir] = useState<string | null>(null);
  const [folders, setFolders] = useState<VaultFolder[] | null>(null);
  if (!s) return <Pane label="jev and vault"><span class="dim">Loading…</span></Pane>;
  return (
    <Pane label="jev and vault" id="set-jev">
      <div class="det">
        <label class="opt"><input type="checkbox" checked={s.use_jev} onChange={(e) => void saveSettings({ use_jev: (e.target as HTMLInputElement).checked })} />
          <span><b>Use jev</b><small>{s.jev_installed ? "jev is installed" : "jev is not installed; hints fall back to plain text"}</small></span></label>
        <Field label="Vault directory"><input value={dir ?? s.vault_dir ?? ""} placeholder="/path/to/obsidian-vault" onInput={(e) => setDir((e.target as HTMLInputElement).value)} onKeyDown={async (e) => { if (e.key === "Enter" && dir !== null && (await saveSettings({ vault_dir: dir || null }))) setDir(null); }} /></Field>
        <div class="acts">
          <Btn primary disabled={dir === null} onClick={async () => { if (await saveSettings({ vault_dir: dir || null })) setDir(null); }}>Save vault</Btn>
          <Btn disabled={!s.vault_dir} onClick={async () => { const r = await mutate(() => http.get<{ folders: VaultFolder[] }>("/api/vault/folders"), null); if (r) setFolders(r.folders); }}>List folders</Btn>
        </div>
        {folders && <div class="log">{folders.map((f) => <span key={f.path} class="mono">{f.path}</span>)}{folders.length === 0 && <span>No folders.</span>}</div>}
      </div>
    </Pane>
  );
}

const GRIND_LABELS: Record<keyof Settings["grind_limits"], string> = {
  max_rounds: "Max rounds", poll_interval: "Poll interval (seconds)", max_wait: "Max wait for a review (seconds)", max_idle_waits: "Idle waits before stopping",
  stuck_seen: "Stop when a finding repeats (times)", ci_timeout: "CI timeout (seconds)", ci_poll: "CI poll interval (seconds)",
};

export function ServerPane() {
  const s = settings.value;
  const [d, setD] = useState<Settings["server"] | null>(null);
  const [gl, setGl] = useState<Settings["grind_limits"] | null>(null);
  const [hosts, setHosts] = useState<string | null>(null);
  if (!s) return <Pane label="server and grind"><span class="dim">Loading…</span></Pane>;
  const v = d ?? s.server;
  const g = gl ?? s.grind_limits;
  const dirty = !!d || !!gl || hosts !== null;
  const num = (k: keyof Settings["grind_limits"]) => (
    <Field label={GRIND_LABELS[k]}><input type="number" min={0} value={g[k]} onInput={(e) => setGl({ ...g, [k]: Number((e.target as HTMLInputElement).value) })} /></Field>
  );
  return (
    <Pane label="server and grind" id="set-server">
      <div class="det">
        <div class="fields">
          <Field label="Port"><input type="number" min={1024} max={65535} value={v.port} onInput={(e) => setD({ ...v, port: Number((e.target as HTMLInputElement).value) })} /></Field>
          <Field label="Tailscale HTTPS port"><select value={v.tailscale_https_port} onChange={(e) => setD({ ...v, tailscale_https_port: Number((e.target as HTMLSelectElement).value) as 443 })}><option>443</option><option>8443</option><option>10000</option></select></Field>
          <label class="opt"><input type="checkbox" checked={v.tailscale} onChange={(e) => setD({ ...v, tailscale: (e.target as HTMLInputElement).checked })} /><span><b>Serve on the tailnet</b></span></label>
        </div>
        <Field label="Allowed hosts (comma separated)"><input placeholder="mac.tail1234.ts.net" value={hosts ?? v.allow_hosts.join(", ")} onInput={(e) => setHosts((e.target as HTMLInputElement).value)} /></Field>
        <span class="dim">Port and tailscale changes apply after a restart.</span>
        <div class="fields">
          <Field label="Grind mode"><select value={s.grind_mode} onChange={(e) => void saveSettings({ grind_mode: (e.target as HTMLSelectElement).value as "deep" })}><option>deep</option><option>simple</option></select></Field>
          {num("max_rounds")}{num("poll_interval")}{num("max_wait")}{num("max_idle_waits")}{num("stuck_seen")}{num("ci_timeout")}{num("ci_poll")}
        </div>
        <div class="acts"><Btn primary disabled={!dirty} onClick={async () => {
          if (await saveSettings({ server: { ...v, allow_hosts: hosts === null ? v.allow_hosts : csv(hosts) }, grind_limits: g })) { setD(null); setGl(null); setHosts(null); }
        }}>Save</Btn>{dirty && <><Btn onClick={() => { setD(null); setGl(null); setHosts(null); }}>Discard</Btn><span class="c-w">Unsaved changes</span></>}</div>
      </div>
    </Pane>
  );
}
