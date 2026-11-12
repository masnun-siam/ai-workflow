import { inboxItems } from "../state/select";
import { ago, shortRepo } from "../state/format";
import { AskForm } from "./AskForm";
import { Pane } from "./ui";

/** Rail + drawer has no always-visible detail pane, so open questions are answered right here, on every screen. */
export function Questions() {
  const qs = inboxItems.value.filter((it) => it.round && it.session_id && it.round.status === "pending");
  if (!qs.length) return null;
  return (
    <Pane label={qs.length === 1 ? "a run is asking you" : `${qs.length} runs are asking you`}>
      <div class="qs">
        {qs.map((it) => (
          <div key={it.key} class="q-item">
            <div class="dh"><b>{it.title}</b></div>
            <span class="dim mono">{shortRepo(it.repo)}{it.at ? ` · ${ago(it.at)}` : ""}{it.links.session && <> · <a href={it.links.session}>Open session</a></>}</span>
            <AskForm key={it.round!.id} sessionId={it.session_id!} round={it.round!} />
          </div>
        ))}
      </div>
    </Pane>
  );
}
