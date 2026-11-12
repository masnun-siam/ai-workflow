import { useState } from "preact/hooks";
import { http } from "../api/http";
import type { Round } from "../api/types";
import { buildAnswers, canSubmit, emptyDraft, toggleLabel, type Draft } from "../state/answer";
import { currentView, loadMany } from "../state/data";
import { visibleKeys } from "../state/refetch";
import { describeError } from "../state/actions";
import { detailOpen, toast } from "../state/ui";
import { Btn } from "./ui";

export async function submitAnswers(sessionId: string, round: Round, drafts: Draft[]): Promise<boolean> {
  const answers = buildAnswers(drafts);
  if (!answers) return false;
  try {
    await http.send("POST", `/api/sessions/${sessionId}/answer`, { round_id: round.id, answers });
    toast("Answered. The run continues");
    detailOpen.value = false;
    void loadMany(visibleKeys(currentView()));
    return true;
  } catch (e) {
    toast(describeError(e), "error");
    return false;
  }
}

/** AskUserQuestion form: single or multi select, free text, several questions. */
export function AskForm({ sessionId, round }: { sessionId: string; round: Round }) {
  const [drafts, setDrafts] = useState<Draft[]>(() => emptyDraft(round));
  const [busy, setBusy] = useState(false);
  const quick = round.questions.length === 1 && !round.questions[0]!.multiSelect;
  const patch = (i: number, d: Draft) => setDrafts(drafts.map((x, j) => (j === i ? d : x)));
  const send = async (ds: Draft[]) => { setBusy(true); await submitAnswers(sessionId, round, ds); setBusy(false); };
  return (
    <form class="ask" aria-label="Question" onSubmit={(e) => { e.preventDefault(); void send(drafts); }}>
      {round.held && <span class="c-w">Held: the away answerer was not sure. It needs you.</span>}
      {round.risk && <span class="dim">Risk {round.risk.p == null ? "unknown" : `${Math.round(round.risk.p * 100)}%`}</span>}
      {round.questions.map((q, i) => {
        const d = drafts[i]!;
        return (
          <fieldset key={i} style={{ border: 0, padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "6px" }}>
            <legend style={{ padding: 0 }}><b>{q.header ? `${q.header}: ` : ""}{q.question}</b>{q.multiSelect && <span class="dim"> (choose any)</span>}</legend>
            {q.options.map((o, oi) => {
              const on = d.labels.includes(o.label);
              if (quick) {
                return (
                  <button type="button" disabled={busy} class={`btn qopt${o.label === q.recommended ? " pri" : ""}`} onClick={() => send([{ labels: [o.label], other: "" }])}>
                    <kbd>{"abc"[oi] ?? ""}</kbd>
                    <b>{o.label}</b>{o.label === q.recommended && <span class="rec">recommended</span>}
                    {o.description && <span class="qd">{o.description}</span>}
                  </button>
                );
              }
              return (
                <label class={`opt${on ? " on" : ""}`}>
                  <input type={q.multiSelect ? "checkbox" : "radio"} name={`q${i}`} checked={on} onChange={() => patch(i, toggleLabel(d, o.label, q.multiSelect))} />
                  <span><b>{o.label}</b>{o.label === q.recommended && <span class="rec"> recommended</span>}
                    {o.description && <small>{o.description}</small>}{o.preview && <pre>{o.preview}</pre>}</span>
                </label>
              );
            })}
            {quick && q.options.some((o) => o.preview) && <pre class="pre dim">{q.options.map((o) => o.preview && `${o.label}:\n${o.preview}`).filter(Boolean).join("\n\n")}</pre>}
            {q.allowFreeText && round.allowFreeText && (
              <label class="fld">Or write your own answer
                <input type="text" value={d.other} onInput={(e) => patch(i, { ...d, other: (e.target as HTMLInputElement).value })}
                  onKeyDown={(e) => { if (e.key === "Enter" && quick && d.other.trim()) { e.preventDefault(); void send([{ labels: [], other: d.other }]); } }} />
              </label>
            )}
          </fieldset>
        );
      })}
      {(!quick || round.questions[0]!.allowFreeText) && <Btn type="submit" primary disabled={busy || !canSubmit(drafts)}>{busy ? "Sending…" : "Send answer"}</Btn>}
    </form>
  );
}
