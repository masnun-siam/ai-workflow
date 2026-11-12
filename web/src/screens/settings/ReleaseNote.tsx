import { useState } from "preact/hooks";
import { settings } from "../../state/data";
import { Btn, Field, Pane } from "../../components/ui";
import { saveSettings } from "./common";
import type { Settings } from "../../api/types";

export function ReleaseNotePane() {
  const s = settings.value;
  const [d, setD] = useState<Settings["release_note"] | null>(null);
  if (!s) return <Pane label="release note"><span class="dim">Loading…</span></Pane>;
  const v = d ?? s.release_note;
  const set = (p: Partial<Settings["release_note"]>) => setD({ ...v, ...p });
  const setCc = (i: number, p: Partial<Settings["release_note"]["cc"][number]>) => set({ cc: v.cc.map((c, j) => (j === i ? { ...c, ...p } : c)) });
  return (
    <Pane label="release note defaults" id="set-release">
      <form class="det" onSubmit={async (e) => { e.preventDefault(); if (await saveSettings({ release_note: v })) setD(null); }}>
        <div class="fields">
          <Field label="Channel name"><input value={v.channel_name} onInput={(e) => set({ channel_name: (e.target as HTMLInputElement).value })} /></Field>
          <Field label="Channel id"><input value={v.channel_id} onInput={(e) => set({ channel_id: (e.target as HTMLInputElement).value })} /></Field>
          <Field label="Name suffix"><input value={v.suffix} onInput={(e) => set({ suffix: (e.target as HTMLInputElement).value })} /></Field>
        </div>
        {v.cc.map((c, i) => (
          <div class="cc-row" key={i}>
            <Field label={`CC ${i + 1} · name`}><input value={c.name} onInput={(e) => setCc(i, { name: (e.target as HTMLInputElement).value })} /></Field>
            <Field label="Slack id"><input value={c.slack_id} onInput={(e) => setCc(i, { slack_id: (e.target as HTMLInputElement).value })} /></Field>
            <Btn small bad title={`Remove CC ${i + 1}`} onClick={() => set({ cc: v.cc.filter((_, j) => j !== i) })}>Remove</Btn>
          </div>
        ))}
        <div class="acts"><Btn onClick={() => set({ cc: [...v.cc, { name: "", slack_id: "" }] })}>Add CC</Btn><Btn type="submit" primary disabled={!d}>Save</Btn>{d && <><Btn onClick={() => setD(null)}>Discard</Btn><span class="c-w">Unsaved changes</span></>}</div>
      </form>
    </Pane>
  );
}
