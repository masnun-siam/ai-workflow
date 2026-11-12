import { useState } from "preact/hooks";
import { http } from "../../api/http";
import type { Effort, Model, Settings } from "../../api/types";
import { mutate, settings } from "../../state/data";
import { Btn, Field, Pane } from "../../components/ui";
import { saveSettings } from "./common";

export function AccountsPane() {
  const s = settings.value;
  const [cmds, setCmds] = useState<Settings["commands"] | null>(null);
  const [msg, setMsg] = useState<Record<string, string>>({});
  if (!s) return <Pane label="accounts" wide><span class="dim">Loading…</span></Pane>;
  const list = cmds ?? s.commands;
  const edit = (i: number, p: Partial<Settings["commands"][number]>) => setCmds(list.map((c, j) => (j === i ? { ...c, ...p } : c)));
  const test = async (label: string) => {
    const r = await mutate(() => http.send<{ ok: boolean; message: string }>("POST", "/api/settings/test-account", { label }), null);
    if (r) setMsg({ ...msg, [label]: `${r.ok ? "ok" : "failed"}: ${r.message}` });
  };
  return (
    <Pane label="accounts" wide id="set-accounts">
      <div class="det">
        <div class="tablewrap"><table class="t"><thead><tr><th>Label</th><th>Command</th><th>Default</th><th /></tr></thead><tbody>
          {list.map((c, i) => (
            <tr key={i}>
              <td><input aria-label="Account label" placeholder="work" value={c.label} disabled={c.builtin} onInput={(e) => edit(i, { label: (e.target as HTMLInputElement).value })} style={{ width: "8em" }} /></td>
              <td><input aria-label="Account command" placeholder="claude" value={c.cmd} disabled={c.builtin} onInput={(e) => edit(i, { cmd: (e.target as HTMLInputElement).value })} style={{ width: "11em" }} /></td>
              <td><input type="radio" name="default-account" aria-label={`${c.label} is the default`} checked={s.default === c.label} onChange={() => void saveSettings({ default: c.label })} /></td>
              <td><div class="acts"><Btn small disabled={!!cmds} title={cmds ? "Save first" : "Run the command once to check it works"} onClick={() => test(c.label)}>Test</Btn>{!c.builtin && <Btn small bad onClick={() => setCmds(list.filter((_, j) => j !== i))}>Remove</Btn>}</div>{msg[c.label] && <span class="dim" role="status">{msg[c.label]}</span>}</td>
            </tr>
          ))}</tbody></table></div>
        <div class="acts"><Btn onClick={() => setCmds([...list, { label: "", cmd: "" }])}>Add account</Btn>
          {cmds && <><Btn primary disabled={cmds.some((c) => !c.label.trim() || !c.cmd.trim())} title={cmds.some((c) => !c.label.trim() || !c.cmd.trim()) ? "Every account needs a label and a command" : undefined} onClick={async () => { if (await saveSettings({ commands: cmds })) setCmds(null); }}>Save accounts</Btn><Btn onClick={() => setCmds(null)}>Discard</Btn><span class="c-w">Unsaved changes</span></>}</div>
        <div class="fields">
          <Field label="Default model"><select value={s.run_model ?? ""} onChange={(e) => void saveSettings({ run_model: ((e.target as HTMLSelectElement).value || null) as Model | null })}><option value="">account default</option><option>opus</option><option>sonnet</option><option>haiku</option></select></Field>
          <Field label="Default effort"><select value={s.run_effort ?? ""} onChange={(e) => void saveSettings({ run_effort: ((e.target as HTMLSelectElement).value || null) as Effort | null })}><option value="">account default</option><option>low</option><option>medium</option><option>high</option><option>xhigh</option><option>max</option></select></Field>
        </div>
      </div>
    </Pane>
  );
}
