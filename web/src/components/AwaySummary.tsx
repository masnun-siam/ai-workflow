/** Old aiw "While you were away": what Away mode answered, held and retried, with Change selected
 *  (send a different answer to a round it answered) and Dismiss. */
import { signal } from "@preact/signals";
import { useRef, useState } from "preact/hooks";
import { http } from "../api/http";
import type { AwayLog, Question } from "../api/types";
import { describeError } from "../state/actions";
import { load, loadMany, mutate, status } from "../state/data";
import { clock, fmtCost, shortRepo } from "../state/format";
import { askConfirm, toast } from "../state/ui";
import { Btn, Tag, useFocusTrap } from "./ui";

/** The Change dialog is a layer: Escape closes it through `closeTopLayer`. */
export const awayChangeOpen = signal(false);

type Row = AwayLog & { id: string };
type Pick = { labels: string[]; other: string };
type Q = Question & { picked: string[]; why: string };

function ChangeDialog({ rows, onClose }: { rows: Row[]; onClose: () => void }) {
  const [picks, setPicks] = useState<Record<string, Pick[]>>(() =>
    Object.fromEntries(rows.map((r) => [r.id, (r.questions ?? []).map((q) => ({ labels: [...q.picked], other: "" }))])));
  const [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box);
  const set = (id: string, qi: number, p: Pick) => setPicks({ ...picks, [id]: picks[id]!.map((x, i) => (i === qi ? p : x)) });
  const changed = rows.filter((r) => (r.questions ?? []).some((q, qi) => { const p = picks[r.id]![qi]!; return p.other.trim() || p.labels.join("|") !== q.picked.join("|"); }));
  const submit = async () => {
    setBusy(true);
    const changes = changed.map((r) => ({ id: r.id, answers: Object.fromEntries(picks[r.id]!.map((p, i) => [String(i), p.other.trim() ? { other: p.other.trim() } : { labels: p.labels }])) }));
    try {
      const res = await http.send<{ sent: string[]; queued: string[]; errors: { sid: string; error: string }[] }>("POST", "/api/away/change", { changes });
      toast(`${res.sent.length} sent${res.queued.length ? `, ${res.queued.length} queued for when the run is free` : ""}${res.errors.length ? `, ${res.errors.length} failed: ${res.errors[0]!.error}` : ""}`, res.errors.length ? "warn" : "info");
      void loadMany(["status", "inbox", "sessions"]);
      onClose();
    } catch (e) { toast(describeError(e), "error"); }
    setBusy(false);
  };
  return (
    <div class="ov" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div class="dlg" ref={box} role="dialog" aria-modal="true" aria-labelledby="chg-h"><div class="form">
        <h2 id="chg-h" class="dlg-h">Change {rows.length === 1 ? "this answer" : `${rows.length} answers`}</h2>
        <span class="dim">The run gets a new message with your answer and why the earlier one was replaced.</span>
        {rows.map((r) => (
          <div key={r.id} class="chg">
            <div class="dim">{shortRepo(r.repo)} · {r.command}</div>
            {((r.questions ?? []) as Q[]).map((q, qi) => {
              const p = picks[r.id]![qi]!;
              return (
                <fieldset key={qi} class="fset">
                  <legend><b>{q.header ? `${q.header}: ` : ""}{q.question}</b>{q.multiSelect && <span class="dim"> (choose any)</span>}</legend>
                  {q.options.map((o) => {
                    const on = p.labels.includes(o.label);
                    return (
                      <label key={o.label} class={`opt${on ? " on" : ""}`}>
                        <input type={q.multiSelect ? "checkbox" : "radio"} name={`${r.id}-${qi}`} checked={on && !p.other}
                          onChange={() => set(r.id, qi, { other: "", labels: q.multiSelect ? (on ? p.labels.filter((l) => l !== o.label) : [...p.labels, o.label]) : [o.label] })} />
                        <span><b>{o.label}</b>{q.picked.includes(o.label) && <span class="dim"> · Away picked this</span>}{o.description && <small>{o.description}</small>}</span>
                      </label>
                    );
                  })}
                  {q.allowFreeText !== false && <input placeholder="Or write your own answer" aria-label="Your own answer" value={p.other} onInput={(e) => set(r.id, qi, { ...p, other: (e.target as HTMLInputElement).value })} />}
                  {q.why && <small class="dim">Why Away picked it: {q.why}</small>}
                </fieldset>
              );
            })}
          </div>
        ))}
        <div class="acts"><Btn primary disabled={!changed.length || busy} onClick={submit}>{busy ? "Sending…" : `Send ${changed.length || ""} new answer${changed.length === 1 ? "" : "s"}`}</Btn><Btn onClick={onClose}>Cancel</Btn></div>
      </div></div>
    </div>
  );
}

export function AwaySummary() {
  const s = status.value?.away.summary;
  const [heldOnly, setHeldOnly] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  if (!s) return null;
  const change = awayChangeOpen.value;
  const log = s.log.filter((e) => !heldOnly || e.kind === "held");
  const answered = s.log.filter((e) => e.kind === "answer").length;
  const retried = s.log.filter((e) => e.kind === "retry").length;
  const cost = s.log.reduce((a, e) => a + (e.cost ?? 0), 0);
  const changeable = (e: AwayLog) => e.kind === "answer" && !!e.id && !e.changed && !!e.questions?.length;
  const rows = log.filter((e): e is Row => !!e.id && picked.has(e.id) && changeable(e));
  const toggle = (id: string) => { const n = new Set(picked); if (n.has(id)) n.delete(id); else n.add(id); setPicked(n); };
  const showHeldOnly = (on: boolean) => { setHeldOnly(on); if (on) setPicked(new Set()); };
  const openChange = async () => {
    if (await askConfirm(`Change ${rows.length === 1 ? "this answer" : `${rows.length} answers`}? Each run gets a new message with your answer.`)) awayChangeOpen.value = true;
  };
  return (
    <section class="pane away-sum" aria-label="While you were away">
      <div class="dh">
        <h2 class="lb">While you were away · {clock(s.started)}–{clock(s.ended)}</h2>
        <span class="dim">{answered} answered · {s.held} held · {retried} retried{cost ? ` · ${fmtCost(cost)}` : ""}</span>
        <span class="grow" />
        <label class="opt inline"><input type="checkbox" checked={heldOnly} onChange={(e) => showHeldOnly((e.target as HTMLInputElement).checked)} /><span>Held only</span></label>
        <Btn small disabled={!rows.length} onClick={openChange}>Change {rows.length || ""} selected</Btn>
        <Btn small onClick={() => mutate(() => http.send("POST", "/api/away/dismiss", {}), "Dismissed", ["status", "inbox"])}>Dismiss</Btn>
      </div>
      <div class="rows">
        {log.map((e) => (
          <div key={e.id ?? `${e.sid}-${e.at}-${e.kind}`} class="irow">
            {changeable(e) ? <input type="checkbox" aria-label={`Pick to change: ${e.question || e.command}`} checked={picked.has(e.id!)} onChange={() => toggle(e.id!)} /> : <span />}
            <Tag tone={e.kind === "held" ? "c-w" : e.kind === "retry" ? "c-q" : "c-o"}>{e.kind === "answer" ? (e.changed ? "changed" : "answered") : e.kind}</Tag>
            <span class="t">
              <span class="dim">{shortRepo(e.repo)}{e.link ? ` #${e.link.issue}` : ""} · </span>{e.question || e.command}
              {e.kind === "answer" && <> → <b>{e.picked}</b></>}
              {e.by && <span class="chip">{e.by === "recommended" ? "Recommended" : "Opus"}</span>}
              {e.risk != null && <span class={e.risk >= 0.5 ? "c-w" : "dim"}> · risk {Math.round(e.risk * 100)}%</span>}
              {e.reason && <span class="dim"> · {e.reason}</span>}
            </span>
            <div class="acts">
              <a href={`#/sessions/${e.sid}`}>session</a>
              {e.answerer && <a href={`#/sessions/${e.answerer}`}>why</a>}
              <span class="dim mono">{clock(e.at)}{e.cost ? ` · ${fmtCost(e.cost)}` : ""}</span>
            </div>
          </div>
        ))}
        {!log.length && <span class="dim">{heldOnly ? "Nothing was held." : "Nothing happened while you were away."}</span>}
      </div>
      {change && <ChangeDialog rows={rows} onClose={() => { awayChangeOpen.value = false; setPicked(new Set()); void load("status"); }} />}
    </section>
  );
}
