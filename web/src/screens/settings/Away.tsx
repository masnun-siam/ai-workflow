import { useState } from "preact/hooks";
import { http } from "../../api/http";
import type { Away } from "../../api/types";
import { AWAY_PRESETS, awayLabel } from "../../state/away";
import { mutate, status } from "../../state/data";
import { Btn, Chips, KV, Pane } from "../../components/ui";

export function AwayPane() {
  const a: Away | undefined = status.value?.away;
  const [m, setM] = useState("240");
  if (!a) return <Pane label="away mode"><span class="dim">Loading…</span></Pane>;
  const call = (path: string, body: object, msg: string) => mutate(() => http.send("POST", path, body), msg, ["status", "inbox"]);
  const label = AWAY_PRESETS.find(([min]) => String(min) === m)?.[1] ?? m;
  return (
    <Pane label="away mode" id="set-away">
      <div class="det">
        <span class="mu">While away, setu answers questions it is confident about and holds the rest for you.</span>
        {a.active ? (
          <>
            <KV rows={[["state", awayLabel(a)], ["answered", a.decisions], ["held", a.held]]} />
            <span class="dim">End Away mode with I'm back in the banner at the top.</span>
          </>
        ) : (
          <div class="acts">
            <Chips label="Away duration" value={m} options={AWAY_PRESETS.map(([min, l]) => [String(min), l] as [string, string])} onPick={setM} />
            <Btn primary onClick={() => call("/api/away", { until: Math.floor(Date.now() / 1000) + Number(m) * 60 }, `Away mode on for ${label}`)}>Go away for {label}</Btn>
          </div>
        )}
        {a.summary && (
          <div><b>Last session</b> · {a.summary.log.length} events, {a.summary.held} held
            <div class="log">{a.summary.log.slice(0, 8).map((l, i) => <span key={l.id ?? `${l.sid}-${l.at}-${i}`}>{l.kind}: {l.question} → {l.picked}</span>)}</div>
            <Btn small onClick={() => call("/api/away/dismiss", {}, "Dismissed")}>Dismiss summary</Btn></div>
        )}
      </div>
    </Pane>
  );
}
