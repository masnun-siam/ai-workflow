import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import { http } from "../api/http";
import type { Session } from "../api/types";
import { continueStalled, loadMany, mutate, transcript } from "../state/data";
import { askConfirm } from "../state/ui";
import { fmtCost, fmtDur, fmtTokens, issueUrl, shortRepo } from "../state/format";
import { AskForm } from "./AskForm";
import { Transcript } from "./Transcript";
import { Btn, Chips, KV, Tag } from "./ui";

export const statusTone = (s: Session["status"]): string =>
  ({ running: "c-q", starting: "c-q", waiting: "c-w", limited: "c-w", queued: "", done: "c-o", failed: "c-b", stopped: "" })[s];

/** The status tag of a session: "Stalled" (warning) in place of its status when it stopped without finishing. */
export const sessionTag = (s: Pick<Session, "status" | "stalled">): [string, string] =>
  s.stalled ? ["Stalled", "c-w"] : [s.status, statusTone(s.status)];

/** Continue a stalled session; a 409 (no longer stalled) reloads the session, the list and the inbox. */
export const continueSession = (id: string) =>
  continueStalled(() => http.send("POST", `/api/sessions/${id}/continue`, {}), ["sessions", "session", "inbox"]);

type SubAction = { sub: string; label: string; when: (s: Session) => boolean; confirm?: string };
const SUBS: SubAction[] = [
  { sub: "continue", label: "Continue", when: (s) => !!s.stalled },
  { sub: "stop", label: "Stop", when: (s) => ["starting", "running", "waiting", "limited", "queued"].includes(s.status), confirm: "Stop this run?" },
  { sub: "resume", label: "Resume", when: (s) => ["limited", "stopped", "failed", "done"].includes(s.status) && !!s.session_id },
  { sub: "start-now", label: "Start now", when: (s) => s.status === "queued" },
  { sub: "hold", label: "Hold", when: (s) => !s.hold && s.status === "queued" },
  { sub: "release", label: "Release hold", when: (s) => s.hold },
  { sub: "cancel-auto", label: "Cancel auto-resume", when: (s) => s.status === "limited" && s.auto_resume === true },
  { sub: "rerun", label: "Rerun", confirm: "Start this run again from the beginning?", when: (s) => ["done", "failed", "stopped"].includes(s.status) },
  { sub: "dismiss", label: "Dismiss", when: (s) => ["done", "failed", "stopped"].includes(s.status) && !s.dismissed },
];

export function SessionView({ s, compact }: { s: Session; compact?: boolean }) {
  const [text, setText] = useState("");
  const [tab, setTab] = useState<"all" | "hook">("all");
  const t = transcript.value.id === s.id ? transcript.value.events : [];
  const working = s.status === "running" || s.status === "starting";
  // When this page last saw a new event; a clock tick re-renders the "Ns ago" while the run is working.
  const [seen, setSeen] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { setSeen(Date.now()); setNow(Date.now()); }, [s.id, t.length]);
  useEffect(() => { if (!working) return; const i = setInterval(() => setNow(Date.now()), 5000); return () => clearInterval(i); }, [working]);
  const run = async (a: SubAction) => {
    if (a.confirm && !(await askConfirm(a.confirm))) return;
    if (a.sub === "continue") return continueSession(s.id);
    await mutate(() => http.send("POST", `/api/sessions/${s.id}/${a.sub}`, {}), `${a.label}: ok`, ["sessions", "session", "inbox"]);
  };
  const sendPrompt = async () => {
    if (!text.trim()) return;
    const r = await mutate(() => http.send<{ state: string }>("POST", `/api/sessions/${s.id}/prompt`, { text }), null);
    if (r) { setText(""); void loadMany(["session"]); }
  };
  const live = ["starting", "running", "waiting"].includes(s.status);
  const finished = ["done", "failed", "stopped"].includes(s.status) && !!s.session_id;
  const canSend = live || finished || s.status === "limited" || s.status === "queued";
  const [tag, tone] = sessionTag(s);
  return (
    <div class="det">
      <div class="dh"><Tag tone={tone}>{tag}</Tag><b>{s.title}</b>{working && <span class="dim grow r">last event {fmtDur((now - seen) / 1000) || "0s"} ago</span>}</div>
      <span class="dim mono">{s.skill ?? "free text"} · {shortRepo(s.repo) || "no repo"}{s.link && <> · <a href={issueUrl(s.link)} target="_blank" rel="noopener noreferrer">#{s.link.issue}</a></>}</span>
      {s.stalled && <div class="banner">Stalled: {s.stalled}</div>}
      {s.error && <div class="banner bad" role="alert">{s.error}</div>}
      {s.status === "limited" && <div class="banner">Rate limited{s.limit_resets_at ? ` until ${new Date(s.limit_resets_at * 1000).toLocaleTimeString()}` : ""}{s.auto_resume ? ". Resumes by itself." : "."}</div>}
      {s.queued_prompt && <div class="dim">Queued message: {s.queued_prompt}</div>}
      {s.pending_answer && <div class="dim">{s.status === "running" || s.status === "starting" ? "Your answer was sent. The run is continuing with it." : "Your answer is saved. It is sent when the run resumes."}</div>}
      {s.pending_question && <AskForm key={s.pending_question.id} sessionId={s.id} round={s.pending_question} />}
      <div class="acts">{SUBS.filter((a) => a.when(s)).map((a) => <Btn key={a.sub} small bad={a.sub === "stop"} primary={a.sub === "continue"} onClick={() => run(a)}>{a.label}</Btn>)}</div>
      {!compact && (
        <details class="meta"><summary>Details</summary>
        <KV rows={[["account", s.account], ["model", `${s.model ?? "default"}${s.effort ? ` · ${s.effort}` : ""}`], ["cost", fmtCost(s.cost) || "n/a"], ["tokens", fmtTokens(s.tokens) || "n/a"],
          ...(s.command.trim() && s.command.trim() !== s.title ? [["prompt", <span class="pre">{s.command.trim()}</span>] as [string, ComponentChildren]] : []),
          ["duration", fmtDur(s.duration_s)], ["hooks", String(s.hooks)], ["id", <span class="mono">{s.id}</span>], ["resume", s.resume_command ? <code>{s.resume_command}</code> : "n/a"]]} />
        </details>
      )}
      {s.panel && <span class="dim">Peer review {s.panel.role}{s.panel.lens ? ` · ${s.panel.lens}` : ""} · {s.panel.state}</span>}
      {s.dispatch && <span class="dim"><a href={`#/dispatches/${s.dispatch.id}?lane=${encodeURIComponent(s.dispatch.lane)}`}>Dispatch {s.dispatch.id} · lane {s.dispatch.lane}</a></span>}
      <Chips label="Transcript view" value={tab} onPick={setTab} options={[["all", "Transcript"], ["hook", `Hooks (${s.hooks})`]]} />
      <Transcript events={t} hooksOnly={tab === "hook"} fill={!compact} />
      {canSend && (
        <form class="acts" onSubmit={(e) => { e.preventDefault(); void sendPrompt(); }}>
          <input type="text" style={{ flex: 1 }} aria-label="Message to the run" placeholder={finished ? "Reply to continue this run" : "Send a message to the run"} value={text} onInput={(e) => setText((e.target as HTMLInputElement).value)} />
          <Btn type="submit" disabled={!text.trim()}>{finished ? "Reply" : "Send"}</Btn>
        </form>
      )}
    </div>
  );
}
