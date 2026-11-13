import { useState } from "preact/hooks";
import { Select } from "../../components/Select";
import { http } from "../../api/http";
import type { Effort, Model, Settings } from "../../api/types";
import { mutate, settings } from "../../state/data";
import { Btn, Field, Pane } from "../../components/ui";
import { useInlineSave, val } from "./common";

export function AccountsPane() {
  const s = settings.value;
  const [cmds, setCmds] = useState<Settings["commands"] | null>(null);
  const [def, setDef] = useState<string | null>(null);
  const [msg, setMsg] = useState<Record<string, string>>({});
  const { save, note } = useInlineSave();
  if (!s) return <Pane label="accounts" wide><span class="dim">Loading…</span></Pane>;
  const list = cmds ?? s.commands;
  const dflt = def ?? s.default;
  const dirty = !!cmds || def !== null;
  const edit = (i: number, p: Partial<Settings["commands"][number]>) => {
    const old = list[i]!;
    if (p.label !== undefined && old.label === dflt) setDef(p.label);
    setMsg({});
    setCmds(list.map((c, j) => (j === i ? { ...c, ...p } : c)));
  };
  const labels = list.map((c) => c.label.trim().toLowerCase());
  const dup = labels.find((l, i) => l && labels.indexOf(l) !== i);
  const blank = list.some((c) => !c.label.trim() || !c.cmd.trim());
  const problem = blank ? "Every account needs a label and a command" : dup ? `Two accounts are labelled "${dup}"` : null;
  const discard = () => { setCmds(null); setDef(null); };
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
              <td><input aria-label="Account label" placeholder="work" value={c.label} disabled={c.builtin} onInput={(e) => edit(i, { label: val(e) })} style={{ width: "8em" }} /></td>
              <td><input aria-label="Account command" placeholder="claude" value={c.cmd} disabled={c.builtin} onInput={(e) => edit(i, { cmd: val(e) })} style={{ width: "11em" }} /></td>
              <td><input type="radio" name="default-account" aria-label={`${c.label} is the default`} checked={dflt === c.label} onChange={() => setDef(c.label)} /></td>
              <td><div class="acts"><Btn small label={`Test account ${c.label}`} disabled={dirty} title={dirty ? "Save first" : "Run the command once to check it works"} onClick={() => test(c.label)}>Test</Btn>
                {!c.builtin && <Btn small bad label={`Remove account ${c.label}`} disabled={dflt === c.label} title={dflt === c.label ? "Pick another default before removing this account" : undefined} onClick={() => { setMsg({}); setCmds(list.filter((_, j) => j !== i)); }}>Remove</Btn>}</div>{msg[c.label] && <span class="dim" role="status">{msg[c.label]}</span>}</td>
            </tr>
          ))}</tbody></table></div>
        <div class="acts"><Btn onClick={() => setCmds([...list, { label: "", cmd: "" }])}>Add account</Btn>
          {dirty && <><Btn primary disabled={!!problem} title={problem ?? undefined} onClick={async () => { if (await save("accounts", { commands: list, default: dflt })) discard(); }}>Save accounts</Btn><Btn onClick={discard}>Discard</Btn><span class="c-w">Unsaved changes</span></>}
          {problem && dirty && <span class="c-b" role="alert">{problem}</span>}{note("accounts")}</div>
        <div class="fields">
          <Field label="Default model"><Select label="Default model" value={s.run_model ?? ""} onChange={(v) => void save("model", { run_model: (v || null) as Model | null })} options={[["", "account default"], ["opus", "opus"], ["sonnet", "sonnet"], ["haiku", "haiku"]]} /></Field>{note("model")}
          <Field label="Default effort"><Select label="Default effort" value={s.run_effort ?? ""} onChange={(v) => void save("effort", { run_effort: (v || null) as Effort | null })} options={[["", "account default"], ["low", "low"], ["medium", "medium"], ["high", "high"], ["xhigh", "xhigh"], ["max", "max"]]} /></Field>{note("effort")}
        </div>
        <label class="opt"><input type="checkbox" name="idle_guard" checked={s.idle_guard} onChange={(e) => void save("idle", { idle_guard: (e.target as HTMLInputElement).checked })} />
          <span><b>Idle guard</b><small>Sends headless skill runs and lanes back to work when they stop early. Applies to sessions started or resumed after the change.</small></span>{note("idle")}</label>
      </div>
    </Pane>
  );
}
