import { useState } from "preact/hooks";
import { settings } from "../../state/data";
import { Btn, Field, Pane } from "../../components/ui";
import { saveSettings, val } from "./common";
import type { Settings } from "../../api/types";

export const SLACK_ID = /^[UW][A-Z0-9]{2,}$/;
const isEmptyCc = (c: { name: string; slack_id: string }) => !c.name.trim() && !c.slack_id.trim();

export function ReleaseNotePane() {
  const s = settings.value;
  const [d, setD] = useState<Settings["release_note"] | null>(null);
  if (!s) return <Pane label="release note"><span class="dim">Loading…</span></Pane>;
  const v = d ?? s.release_note;
  const set = (p: Partial<Settings["release_note"]>) => setD({ ...v, ...p });
  const setCc = (i: number, p: Partial<Settings["release_note"]["cc"][number]>) => set({ cc: v.cc.map((c, j) => (j === i ? { ...c, ...p } : c)) });
  const cc = v.cc.filter((c) => !isEmptyCc(c)).map((c) => ({ name: c.name.trim(), slack_id: c.slack_id.trim() }));
  const idError = (c: { name: string; slack_id: string }) => (isEmptyCc(c) || SLACK_ID.test(c.slack_id.trim()) ? null : "A Slack member id looks like U01ABC23DEF");
  const invalid = v.cc.some((c) => idError(c));
  return (
    <Pane label="release note defaults" id="set-release">
      <form class="det" onSubmit={async (e) => { e.preventDefault(); if (await saveSettings({ release_note: { ...v, cc } })) setD(null); }}>
        <div class="fields">
          <Field label="Channel name"><input value={v.channel_name} onInput={(e) => set({ channel_name: (e.target as HTMLInputElement).value })} /></Field>
          <Field label="Channel id"><input value={v.channel_id} onInput={(e) => set({ channel_id: (e.target as HTMLInputElement).value })} /></Field>
          <Field label="Name suffix"><input value={v.suffix} onInput={(e) => set({ suffix: (e.target as HTMLInputElement).value })} /></Field>
        </div>
        {v.cc.map((c, i) => (
          <div class="cc-row" key={i}>
            <Field label={`CC ${i + 1} · name`}><input value={c.name} onInput={(e) => setCc(i, { name: (e.target as HTMLInputElement).value })} /></Field>
            <Field label="Slack id" error={d ? idError(c) : null}><input value={c.slack_id} aria-invalid={!!d && !!idError(c)} onInput={(e) => setCc(i, { slack_id: val(e) })} /></Field>
            <Btn small bad title={`Remove CC ${i + 1}`} onClick={() => set({ cc: v.cc.filter((_, j) => j !== i) })}>Remove</Btn>
          </div>
        ))}
        <div class="acts"><Btn onClick={() => set({ cc: [...v.cc, { name: "", slack_id: "" }] })}>Add CC</Btn><Btn type="submit" primary disabled={!d || invalid} title={invalid ? "Fix the Slack ids first" : undefined}>Save</Btn>{d && <><Btn onClick={() => setD(null)}>Discard</Btn><span class="c-w">Unsaved changes</span></>}</div>
      </form>
    </Pane>
  );
}
