import { useState } from "preact/hooks";
import { Select } from "../../components/Select";
import { http } from "../../api/http";
import type { Settings, VaultFolder } from "../../api/types";
import { mutate, settings } from "../../state/data";
import { Btn, Field, Pane } from "../../components/ui";
import { csv, intError, saveSettings, useInlineSave, val } from "./common";

export function JevVaultPane() {
  const s = settings.value;
  const [dir, setDir] = useState<string | null>(null);
  const [folders, setFolders] = useState<VaultFolder[] | null>(null);
  const { save, note } = useInlineSave();
  if (!s) return <Pane label="jev and vault"><span class="dim">Loading…</span></Pane>;
  return (
    <Pane label="jev and vault" id="set-jev">
      <div class="det">
        <label class="opt"><input type="checkbox" checked={s.use_jev} onChange={(e) => void save("jev", { use_jev: (e.target as HTMLInputElement).checked })} />
          <span><b>Use jev</b><small>{s.jev_installed ? "jev is installed" : "jev is not installed; hints fall back to plain text"}</small></span>{note("jev")}</label>
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
const GRIND_KEYS = Object.keys(GRIND_LABELS) as (keyof Settings["grind_limits"])[];
const RANGE: Record<string, [number, number]> = { port: [1024, 65535], ...Object.fromEntries(GRIND_KEYS.map((k) => [k, [1, 86400]])) };

export function ServerPane() {
  const s = settings.value;
  const [d, setD] = useState<Settings["server"] | null>(null);
  const [nums, setNums] = useState<Record<string, string>>({});
  const [gm, setGm] = useState<Settings["grind_mode"] | null>(null);
  const [hosts, setHosts] = useState<string | null>(null);
  if (!s) return <Pane label="server and grind"><span class="dim">Loading…</span></Pane>;
  const v = d ?? s.server;
  const cur: Record<string, number> = { port: v.port, ...s.grind_limits };
  const raw = (k: string) => nums[k] ?? String(cur[k]);
  const err = (k: string) => intError(raw(k), RANGE[k]![0], RANGE[k]![1]);
  const invalid = Object.keys(RANGE).some((k) => err(k));
  const dirty = !!d || gm !== null || hosts !== null || Object.keys(nums).length > 0;
  const reset = () => { setD(null); setNums({}); setGm(null); setHosts(null); };
  const num = (k: string, label: string) => (
    <Field label={label} error={nums[k] !== undefined ? err(k) : null}>
      <input type="number" min={RANGE[k]![0]} max={RANGE[k]![1]} value={raw(k)} aria-invalid={nums[k] !== undefined && !!err(k)} onInput={(e) => setNums({ ...nums, [k]: val(e) })} />
    </Field>
  );
  const submit = async () => {
    const limits = Object.fromEntries(GRIND_KEYS.map((k) => [k, Number(raw(k))])) as Settings["grind_limits"];
    const patch: Partial<Settings> = { server: { ...v, port: Number(raw("port")), allow_hosts: hosts === null ? v.allow_hosts : csv(hosts) }, grind_limits: limits };
    if (gm !== null) patch.grind_mode = gm;
    if (await saveSettings(patch)) reset();
  };
  return (
    <Pane label="server and grind" id="set-server">
      <div class="det">
        <div class="fields">
          {num("port", "Port")}
          <Field label="Tailscale HTTPS port"><Select label="Tailscale HTTPS port" value={String(v.tailscale_https_port)} onChange={(x) => setD({ ...v, tailscale_https_port: Number(x) as 443 })} options={[["443", "443"], ["8443", "8443"], ["10000", "10000"]]} /></Field>
          <label class="opt"><input type="checkbox" checked={v.tailscale} onChange={(e) => setD({ ...v, tailscale: (e.target as HTMLInputElement).checked })} /><span><b>Serve on the tailnet</b></span></label>
        </div>
        <Field label="Allowed hosts (comma separated)"><input placeholder="mac.tail1234.ts.net" value={hosts ?? v.allow_hosts.join(", ")} onInput={(e) => setHosts(val(e))} /></Field>
        <span class="dim">Port and tailscale changes apply after a restart.</span>
        <div class="fields">
          <Field label="Grind mode"><Select label="Grind mode" value={gm ?? s.grind_mode} onChange={(x) => setGm(x as Settings["grind_mode"])} options={[["deep", "deep"], ["simple", "simple"]]} /></Field>
          {GRIND_KEYS.map((k) => num(k, GRIND_LABELS[k]))}
        </div>
        <div class="acts"><Btn primary disabled={!dirty || invalid} title={invalid ? "Fix the fields marked in red first" : undefined} onClick={submit}>Save</Btn>
          {dirty && <><Btn onClick={reset}>Discard</Btn><span class="c-w">Unsaved changes</span></>}
          {invalid && <span class="c-b" role="alert">Fix the fields marked in red to save.</span>}</div>
      </div>
    </Pane>
  );
}
