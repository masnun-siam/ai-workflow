import { prefs, setPref } from "../../state/prefs";
import { Kbd, Pane } from "../../components/ui";

const GROUPS = [
  { key: "look", label: "Look", hotkey: "s", opts: [["console", "Console", "mono, amber, boxed panes"], ["river", "River", "navy, rounded cards"]] },
  { key: "mode", label: "Mode", hotkey: ".", opts: [["system", "System", "follow the OS"], ["dark", "Dark", ""], ["light", "Light", ""]] },
  { key: "layout", label: "Layout", hotkey: "L", opts: [["drawer", "Rail + drawer", "details slide in over the page"], ["split", "Tabs + split", "detail pane always visible"]] },
] as const;

export function Appearance() {
  return (
    <Pane label="appearance" wide id="set-appearance">
      <div class="det">
        {GROUPS.map((g) => (
          <div class="seg-row" key={g.key}>
            <span class="seg-l" id={`seg-${g.key}`}>{g.label} <Kbd>{g.hotkey}</Kbd></span>
            <div class="seg" role="radiogroup" aria-labelledby={`seg-${g.key}`}>
              {g.opts.map(([v, name, hint]) => {
                const on = prefs.value[g.key] === v;
                return (
                  <button key={v} type="button" class={`seg-o${on ? " on" : ""}`} role="radio" aria-checked={on} onClick={() => setPref(g.key, v as never)}>
                    <b>{name}</b>{hint && <span>{hint}</span>}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
        <span class="dim">Saved on this browser. Combine any look with any layout and mode.</span>
      </div>
    </Pane>
  );
}
