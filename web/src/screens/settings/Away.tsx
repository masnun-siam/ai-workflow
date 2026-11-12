import { useState } from "preact/hooks";
import { http } from "../../api/http";
import type { Away } from "../../api/types";
import { mutate, status } from "../../state/data";
import { Btn, Chips, KV, Pane } from "../../components/ui";

const HOURS: [string, string][] = [["1", "1h"], ["2", "2h"], ["4", "4h"], ["8", "8h"], ["16", "16h"]];

export function AwayPane() {
  const a: Away | undefined = status.value?.away;
  const [h, setH] = useState("4");
  if (!a) return <Pane label="away mode"><span class="dim">Loading…</span></Pane>;
  const call = (path: string, body: object, msg: string) => mutate(() => http.send("POST", path, body), msg, ["status", "inbox"]);
  return (
    <Pane label="away mode" id="set-away">
      <div class="det">
        <span class="mu">While away, setu answers questions it is confident about and holds the rest for you.</span>
        {a.active ? (
          <>
            <KV rows={[["until", a.until ? new Date(a.until * 1000).toLocaleString() : "open"], ["answered", a.decisions], ["held", a.held]]} />
            <div class="acts"><Btn primary onClick={() => call("/api/away/stop", {}, "Away mode ended")}>I am back</Btn></div>
          </>
        ) : (
          <div class="acts">
            <Chips label="Away duration" value={h} options={HOURS} onPick={setH} />
            <Btn primary onClick={() => call("/api/away", { until: Math.floor(Date.now() / 1000) + Number(h) * 3600 }, `Away mode on for ${h}h`)}>Go away for {h}h</Btn>
          </div>
        )}
        {a.summary && (
          <div><b>Last session</b> · {a.summary.log.length} events, {a.summary.held} held
            <div class="log">{a.summary.log.slice(0, 8).map((l, i) => <span key={i}>{l.kind}: {l.question} → {l.picked}</span>)}</div>
            <Btn small onClick={() => call("/api/away/dismiss", {}, "Dismissed")}>Dismiss summary</Btn></div>
        )}
      </div>
    </Pane>
  );
}
