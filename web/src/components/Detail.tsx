import type { Action, Card, InboxItem, OpsRow, Round, Session } from "../api/types";
import { AskForm } from "./AskForm";
import { ActionBar } from "./ActionBar";
import { SessionView, statusTone } from "./SessionView";
import { Empty, Tag } from "./ui";
import { nav } from "../state/route";
import { ago } from "../state/format";

export type Target =
  | { kind: "card"; card: Card }
  | { kind: "inbox"; item: InboxItem }
  | { kind: "session"; session: Session }
  | { kind: "ops"; row: OpsRow }
  | null;

export const targetActions = (t: Target): readonly Action[] =>
  !t ? [] : t.kind === "card" ? t.card.actions : t.kind === "inbox" ? t.item.actions : t.kind === "ops" ? t.row.actions : [];

/** The round answerable from this target, with its session id. */
export function targetRound(t: Target): { sessionId: string; round: Round } | null {
  if (!t) return null;
  if (t.kind === "card" && t.card.need && t.card.ask) return { sessionId: t.card.ask.session_id, round: t.card.ask.round };
  if (t.kind === "inbox" && t.item.round && t.item.session_id) return { sessionId: t.item.session_id, round: t.item.round };
  if (t.kind === "session" && t.session.pending_question) return { sessionId: t.session.id, round: t.session.pending_question };
  return null;
}
export const targetId = (t: Target): string | undefined =>
  !t ? undefined : t.kind === "card" ? t.card.id : t.kind === "inbox" ? t.item.key : t.kind === "session" ? t.session.id : t.row.step;

const Links = ({ links }: { links: Card["links"] }) => (
  <div class="acts">
    {links.issue && <a href={links.issue} target="_blank" rel="noopener noreferrer">issue</a>}
    {links.pr && <a href={links.pr} target="_blank" rel="noopener noreferrer">pull request</a>}
    {links.session && <a href={links.session}>Open session</a>}
    {links.prd && <a href={links.prd}>PRD</a>}
  </div>
);

export function Detail({ t }: { t: Target }) {
  if (!t) return <Empty>Select an item to see its details and actions.</Empty>;
  if (t.kind === "session") {
    return <div><div class="acts"><a href={`#/sessions/${t.session.id}`} onClick={(e) => { e.preventDefault(); nav(`#/sessions/${t.session.id}`); }}>Open full page</a></div><SessionView s={t.session} compact /></div>;
  }
  const ask = targetRound(t);
  if (t.kind === "ops") {
    return (
      <div class="det"><div class="dh"><b>{t.row.label}</b></div><span class="dim">{t.row.scope} · {t.row.summary}</span>
        <table class="t"><tbody>{t.row.targets.map((x) => (
          <tr><td class="mono">{x.repo}</td><td>{x.last ? <Tag tone={statusTone(x.last.status)}>{x.last.status}</Tag> : "never"}</td><td>{x.note}</td></tr>))}</tbody></table>
        <ActionBar actions={t.row.actions} /></div>
    );
  }
  const title = t.kind === "card" ? t.card.title : t.item.title;
  const tag = t.kind === "card" ? t.card.tag : t.item.kind;
  const tone = t.kind === "card" ? t.card.tone : "c-w";
  const log = (t.kind === "card" ? t.card.log : t.item.detail) ?? [];
  const note = t.kind === "card" ? (t.card.need ? t.card.note : null) : (t.item.note ?? null);
  const links = t.kind === "card" ? t.card.links : t.item.links;
  return (
    <div class="det">
      <div class="dh"><Tag tone={tone}>{tag}</Tag><b>{title}</b></div>
      <span class="dim mono">
        {t.kind === "card" ? `${t.card.skill || "—"} · ${t.card.repo}` : `${t.item.type}${t.item.repo ? ` · ${t.item.repo}` : ""}${t.item.at ? ` · ${ago(t.item.at)}` : ""}`}
      </span>
      {log.length > 0 && !ask && <div class="log">{log.map((l, i) => <span key={i}>{l}</span>)}</div>}
      {ask && <AskForm key={ask.round.id} sessionId={ask.sessionId} round={ask.round} />}
      {note && <pre class="note">{note}</pre>}
      <Links links={links} />
      <ActionBar actions={ask ? targetActions(t).filter((a) => !(a.open && a.label === "Answer")) : targetActions(t)} dropId={targetId(t)} />
    </div>
  );
}
