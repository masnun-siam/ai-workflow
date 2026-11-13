/** The old aiw issue / PR side panel. Any GitHub issue or PR link of a registered repo opens it
 *  (modified clicks and `data-ext` links still go to GitHub). */
import { signal } from "@preact/signals";
import { useEffect, useRef, useState } from "preact/hooks";
import { http } from "../api/http";
import type { IssueView, PRView } from "../api/types";
import { describeError } from "../state/actions";
import { grinds, loadMany, mutate, repoList, sessionList } from "../state/data";
import { ago, shortRepo } from "../state/format";
import { askConfirm } from "../state/ui";
import { sessionTag } from "./SessionView";
import { Btn, Tag, useFocusTrap } from "./ui";

export type WorkTarget = { kind: "issue" | "pr"; repo: string; n: number };
export const workTarget = signal<WorkTarget | null>(null);

const GH = /^https:\/\/github\.com\/([\w.-]+\/[\w.-]+)\/(issues|pull)\/(\d+)\/?(?:[?#].*)?$/;
/** The panel target for a link, when it is an issue or PR of a registered repo. */
export function ghTarget(href: string): WorkTarget | null {
  const m = GH.exec(href);
  if (!m) return null;
  const repo = repoList.peek().find((r) => r.slug.toLowerCase() === m[1]!.toLowerCase())?.slug;
  return repo ? { kind: m[2] === "pull" ? "pr" : "issue", repo, n: Number(m[3]) } : null;
}

/** Installs the document click handler; returns its remover. */
export function interceptGitHubLinks(): () => void {
  const on = (e: MouseEvent) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = (e.target as Element | null)?.closest?.<HTMLAnchorElement>("a[href]:not([data-ext])");
    const t = a && ghTarget(a.href);
    if (!t || a.closest("[role=dialog]:not(.wpanel),[role=alertdialog]")) return;
    e.preventDefault();
    workTarget.value = t;
  };
  document.addEventListener("click", on);
  return () => document.removeEventListener("click", on);
}

const Html = ({ html }: { html: string }) => (html ? <div class="gh-body" dangerouslySetInnerHTML={{ __html: html }} /> : <p class="dim">No description.</p>);

function Comment({ t }: { t: WorkTarget }) {
  const [text, setText] = useState("");
  const base = `/api/${t.kind === "pr" ? "pulls" : "issues"}/${t.repo}/${t.n}`;
  return (
    <form class="form" onSubmit={async (e) => { e.preventDefault(); if (text.trim() && (await mutate(() => http.send("POST", `${base}/comment`, { text: text.trim() }), "Comment posted"))) { setText(""); reload(); } }}>
      <textarea rows={3} aria-label="Comment" placeholder="Leave a comment on GitHub" value={text} onInput={(e) => setText((e.target as HTMLTextAreaElement).value)} />
      <div class="acts"><Btn small type="submit" disabled={!text.trim()}>Comment</Btn></div>
    </form>
  );
}

let reload = () => {};

function Sessions({ t }: { t: WorkTarget }) {
  const rows = (sessionList.value?.sessions ?? []).filter((s) => s.link && `${s.link.owner}/${s.link.repo}`.toLowerCase() === t.repo.toLowerCase() && s.link.issue === t.n).slice(0, 8);
  if (!rows.length) return null;
  return (
    <div><div class="gh">Sessions</div>
      {rows.map((s) => <a key={s.id} class="row" href={`#/sessions/${s.id}`} onClick={() => (workTarget.value = null)}><span class={`tag ${sessionTag(s)[1]}`}>{sessionTag(s)[0]}</span><span class="t">{s.skill ?? "free text"}</span><span class="w">{ago(s.started_at)}</span></a>)}
    </div>
  );
}

function IssueBody({ t, v }: { t: WorkTarget; v: IssueView }) {
  const state = (s: string, reason?: string) => mutate(() => http.send("POST", `/api/issues/${t.repo}/${t.n}/state`, { state: s, reason }), s === "open" ? "Reopened" : "Closed", ["features", "changes", "river", "inbox"]).then((r) => { if (r) reload(); });
  const refine = () => mutate(() => http.send("POST", "/api/sessions", { step: "refine-issues", repo: t.repo, issue: t.n, args: String(t.n), guard: true }), `Started refine-issues #${t.n}`, ["sessions"]);
  const open = v.state.toLowerCase() === "open";
  return (
    <>
      <div class="dh"><Tag tone={open ? "c-o" : ""}>{open ? "open" : `closed${v.state_reason ? ` · ${v.state_reason.toLowerCase().replace("_", " ")}` : ""}`}</Tag>
        {v.labels.map((l) => <span key={l.name} class="chip">{l.name}</span>)}<span class="dim">by {v.author} · {ago(v.created_at)}</span></div>
      <div class="acts">
        {open && <Btn small primary onClick={refine}>Refine</Btn>}
        {open && <Btn small onClick={async () => { if (await askConfirm(`Close #${t.n} as completed?`)) await state("closed", "completed"); }}>Close as completed</Btn>}
        {open && <Btn small onClick={async () => { if (await askConfirm(`Close #${t.n} as not planned?`)) await state("closed", "not_planned"); }}>Close as not planned</Btn>}
        {!open && <Btn small onClick={() => state("open")}>Reopen</Btn>}
      </div>
      <Html html={v.body_html} />
      <Sessions t={t} />
      {v.comments.length > 0 && <div class="gh">Comments · {v.comment_count}</div>}
      {v.comments.map((c, i) => <div key={i} class="gh-comment"><div class="dim"><b>{c.author}</b> · {ago(c.created_at)}</div><Html html={c.body_html} /></div>)}
      <Comment t={t} />
    </>
  );
}

function PRBody({ t, v }: { t: WorkTarget; v: PRView }) {
  const red = v.checks.filter((c) => c.bucket === "red");
  const pending = v.checks.filter((c) => c.bucket === "pending");
  const g = (grinds.value ?? []).find((x) => x.pr === t.n && x.repo.toLowerCase() === t.repo.toLowerCase());
  const warnings = [v.conflict && "it has merge conflicts", red.length && `${red.length} checks fail`, pending.length && `${pending.length} checks are still running`, v.state === "draft" && "it is a draft"].filter(Boolean) as string[];
  const merge = async () => {
    const q = warnings.length ? `Merge #${t.n} anyway? ${warnings.join(", ")}.` : `Merge #${t.n} into ${v.base}?`;
    if (!(await askConfirm(q))) return;
    if (await mutate(() => http.send("POST", `/api/pulls/${t.repo}/${t.n}/merge`, { sha: v.head_sha }), `Merged #${t.n}`, ["features", "changes", "river", "inbox", "dispatches"])) reload();
  };
  const state = (s: string) => mutate(() => http.send("POST", `/api/pulls/${t.repo}/${t.n}/state`, { state: s }), s === "open" ? "Reopened" : "Closed").then((r) => { if (r) reload(); });
  const live = v.state === "open" || v.state === "draft";
  return (
    <>
      <div class="dh"><Tag tone={v.state === "merged" ? "c-o" : v.state === "closed" ? "" : v.conflict ? "c-b" : "c-q"}>{v.state}{v.conflict ? " · conflict" : ""}</Tag>
        <span class="mono dim">{v.head} → {v.base}</span><span class="dim">by {v.author} · +{v.additions} −{v.deletions} · {v.files.length} files</span></div>
      <div class="acts">
        {live && <Btn small primary={!warnings.length} onClick={merge}>Merge…</Btn>}
        {live && <Btn small onClick={async () => { if (await askConfirm(`Close PR #${t.n} without merging?`)) await state("closed"); }}>Close PR…</Btn>}
        {v.state === "closed" && <Btn small onClick={() => state("open")}>Reopen PR</Btn>}
      </div>
      {warnings.length > 0 && live && <div class="banner">Before merging: {warnings.join(", ")}.</div>}
      {g && (
        <div class="gh-card"><b>Grind</b> <Tag tone={g.state === "running" ? "c-q" : g.state === "paused" ? "c-w" : "c-o"}>{g.state}</Tag> <span class="dim">round {g.rounds}{g.reason ? ` · ${g.reason}` : ""}</span>
          <div class="acts">
            {g.session && <a class="btn sm" href={`#/sessions/${g.session}`} onClick={() => (workTarget.value = null)}>Session</a>}
            {g.thread && <a class="btn sm" href={g.thread} data-ext target="_blank" rel="noreferrer">Slack thread</a>}
            <Btn small onClick={() => mutate(() => http.send("POST", `/api/grinds/${t.repo}/${t.n}/skip-ci`, {}), "CI wait skipped", ["grinds"])}>Skip CI</Btn>
            <Btn small bad onClick={async () => { if (await askConfirm(`Stop grinding #${t.n}?`)) await mutate(() => http.send("POST", `/api/grinds/${t.repo}/${t.n}/stop`, {}), "Grind stopped", ["grinds"]); }}>Stop</Btn>
          </div>
        </div>
      )}
      {v.checks.length > 0 && (
        <div><div class="gh">Checks</div>
          <div class="chips">{v.checks.map((c) => <a key={c.name} class={`chip ${c.bucket === "green" ? "c-o" : c.bucket === "red" ? "c-b" : "c-w"}`} href={c.link} data-ext target="_blank" rel="noreferrer">{c.name}</a>)}</div>
        </div>
      )}
      <Html html={v.body_html} />
      <details><summary class="gh">Files · {v.files.length}</summary>{v.files.map((f) => <div key={f.path} class="mono small"><span class="c-o">+{f.additions}</span> <span class="c-b">−{f.deletions}</span> {f.path}</div>)}</details>
      {v.conversation.length > 0 && <div class="gh">Conversation</div>}
      {v.conversation.map((c, i) => <div key={i} class="gh-comment"><div class="dim"><b>{c.author}</b>{c.state ? ` · ${c.state.toLowerCase().replace("_", " ")}` : ""} · {ago(c.at)}</div><Html html={c.body_html} /></div>)}
      <Comment t={t} />
    </>
  );
}

export function WorkPanel() {
  const t = workTarget.value!;
  const [v, setV] = useState<IssueView | PRView | null>(null);
  const [err, setErr] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useFocusTrap(box, true);
  const get = () => { setErr(""); http.get<IssueView | PRView>(`/api/${t.kind === "pr" ? "pulls" : "issues"}/${t.repo}/${t.n}`).then(setV, (e) => setErr(describeError(e))); };
  reload = () => { get(); void loadMany(["features", "changes"]); };
  useEffect(() => { setV(null); get(); }, [t.kind, t.repo, t.n]);
  const url = `https://github.com/${t.repo}/${t.kind === "pr" ? "pull" : "issues"}/${t.n}`;
  return (
    <>
      <div class="scrim" onClick={() => (workTarget.value = null)} />
      <div class="drawer wpanel" ref={box} tabIndex={-1} role="dialog" aria-modal="true" aria-label={`${t.kind === "pr" ? "Pull request" : "Issue"} #${t.n}`}
        onKeyDown={(e) => { if (e.key === "Escape") { workTarget.value = null; e.stopPropagation(); } }}>
        <div class="drawer-top"><Btn small onClick={() => (workTarget.value = null)}>Close</Btn><span class="dim mono">{shortRepo(t.repo)} {t.kind === "pr" ? "PR" : "issue"} #{t.n}</span><a href={url} data-ext target="_blank" rel="noreferrer">Open on GitHub ↗</a></div>
        <div class="form">
          {err && <div class="banner bad" role="alert">{err}</div>}
          {!v && !err && <span class="dim">Loading from GitHub…</span>}
          {v && <h2 class="dlg-h wp-title">{v.title}</h2>}
          {v && (t.kind === "pr" ? <PRBody t={t} v={v as PRView} /> : <IssueBody t={t} v={v as IssueView} />)}
        </div>
      </div>
    </>
  );
}
