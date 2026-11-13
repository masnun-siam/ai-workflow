import { computed, signal } from "@preact/signals";
import { useEffect, useState } from "preact/hooks";
import { http } from "../api/http";
import type { Release, ReleaseStage } from "../api/types";
import { currentRepo, loadErrors, mutate, releases, settings } from "../state/data";
import { askConfirm } from "../state/ui";
import { ago } from "../state/format";
import { Header } from "../components/Header";
import { ActionBar } from "../components/ActionBar";
import { Btn, Chips, Empty, KV, Pane } from "../components/ui";

/** The repository chip picked on this page; it applies only while the current repo is the one it was picked under. */
const relRepo = signal<{ under: string | null; repo: string } | null>(null);
const editing = signal(false);
const DONE = new Set<ReleaseStage>(["done", "skipped", "failed"]);

const repoList = computed(() => releases.value?.repos ?? []);
const has = (slug: string | null | undefined): slug is string => !!slug && repoList.value.some((r) => r.repo === slug);
const repoSlug = computed(() => {
  const picked = relRepo.value?.under === currentRepo.value ? relRepo.value?.repo : null;
  if (has(picked)) return picked;
  if (has(currentRepo.value)) return currentRepo.value;
  return repoList.value[0]?.repo ?? null;
});
/** The release in flight for the repo, else the newest one. */
export const currentRelease = computed<Release | null>(() => {
  const all = (releases.value?.releases ?? []).filter((r) => r.repo === repoSlug.value);
  return all.find((r) => !DONE.has(r.stage)) ?? all[0] ?? null;
});

const KEYS = ["releases"] as const;
export const releaseOps = {
  cut: (dry: boolean) => mutate(() => http.send("POST", "/api/releases", { repo: repoSlug.value, dry_run: dry || undefined }), dry ? "Dry run started" : "Started release-pr", [...KEYS, "river"]),
  grind: () => { const r = currentRelease.value; return r && mutate(() => http.send("POST", `/api/releases/${r.id}/grind`, {}), "Grind started", [...KEYS]); },
  note: () => { const r = currentRelease.value; return r && mutate(() => http.send("POST", `/api/releases/${r.id}/note`, {}), "Drafting the note", [...KEYS]); },
  skip: async () => { const r = currentRelease.value; if (r && (await askConfirm("Skip this release?", true))) await mutate(() => http.send("POST", `/api/releases/${r.id}/skip`, {}), "Skipped", [...KEYS, "river"]); },
  post: async () => {
    const r = currentRelease.value; if (!r || r.note_posted_at || !r.note) return;
    const ch = settings.value?.release_note.channel_name ?? "the channel";
    if (await askConfirm(`Post the note to #${ch}? It posts once and is never retried.`, true)) await mutate(() => http.send("POST", `/api/releases/${r.id}/post`, {}), `Posted to #${ch}`, [...KEYS, "river", "inbox"]);
  },
  edit: () => { const r = currentRelease.value; if (r && !r.note_posted_at) editing.value = true; },
};
/** Screen keys c y g n p e x. Returns true when handled. */
export function releaseKey(k: string): boolean {
  const map: Record<string, () => unknown> = { c: () => releaseOps.cut(false), y: () => releaseOps.cut(true), g: releaseOps.grind, n: releaseOps.note, p: releaseOps.post, e: releaseOps.edit, x: releaseOps.skip };
  const f = map[k]; if (!f) return false; void f(); return true;
}

const STEPS: { id: string; name: string; hint: (r: Release | null) => string }[] = [
  { id: "cut", name: "Cut", hint: (r) => (r?.pr ? `release-pr · PR #${r.pr}` : "release-pr") },
  { id: "grind", name: "Grind", hint: (r) => (r?.grind ? `pr-grind · ${r.grind.state} r${r.grind.rounds}` : "pr-grind") },
  { id: "merge", name: "Merge", hint: (r) => (r?.merged_at ? `you · ${ago(r.merged_at)}` : "you merge the PR") },
  { id: "notify", name: "Notify", hint: (r) => (r?.note_posted_at ? `posted ${ago(r.note_posted_at)}` : "release-note") },
];
export function stepIndex(stage: ReleaseStage): number {
  return ({ cut: 0, grind: 1, merge: 2, notify: 3, done: 4, skipped: -1, failed: -1, dry_run: -1 } as Record<string, number>)[stage] ?? -1;
}

function NoteEditor({ r }: { r: Release }) {
  const [text, setText] = useState(r.note ?? "");
  useEffect(() => setText(r.note ?? ""), [r.id]);
  const save = async () => { if (await mutate(() => http.send("PUT", `/api/releases/${r.id}/note`, { text }), "Note saved", [...KEYS])) editing.value = false; };
  return (
    <div class="det">
      <textarea aria-label="Release note" rows={10} value={text} maxLength={8000} onInput={(e) => setText((e.target as HTMLTextAreaElement).value)} />
      <div class="acts"><Btn primary onClick={() => save()}>Save</Btn><Btn onClick={() => (editing.value = false)}>Cancel</Btn></div>
    </div>
  );
}

export function Releases() {
  const r = currentRelease.value;
  const idx = r ? stepIndex(r.stage) : -1;
  const posted = !!r?.note_posted_at;
  const repo = repoList.value.find((x) => x.repo === repoSlug.value);
  const err = loadErrors.value.releases;
  const cutWhy = !repo ? "No repository with releases" : repo.open ? "A release is already in flight for this repository" : "Open a release PR";
  return (
    <>
      <Header title="Releases" products>
        <Btn k="c" onClick={() => releaseOps.cut(false)} disabled={!repo || !!repo.open} title={cutWhy}>Cut release</Btn>
        <Btn k="y" onClick={() => releaseOps.cut(true)} disabled={!repo || !!repo.open} title={cutWhy}>Dry run</Btn>
        <Btn k="g" onClick={() => releaseOps.grind()} disabled={!r} title={r ? "Grind the release PR" : "No release yet"}>Grind</Btn>
        <Btn k="n" onClick={() => releaseOps.note()} disabled={!r || posted} title={!r ? "No release yet" : posted ? "The note is already posted" : "Draft the release note"}>Note</Btn>
      </Header>
      {err && <div class="banner bad" role="alert">{err}</div>}
      {repoList.value.length > 0 && <Chips label="Repository" value={repoSlug.value ?? ""} options={repoList.value.map((x) => [x.repo, `${x.name}${x.ahead ? ` (${x.ahead})` : ""}`])} onPick={(v) => { relRepo.value = { under: currentRepo.value, repo: v }; editing.value = false; }} />}
      {repo && <span class="mu">{repo.repo} · {repo.head} → {repo.base}{repo.last_release ? ` · last #${repo.last_release.pr} ${ago(repo.last_release.merged_at)}` : ""}</span>}
      <div class="steps" role="list" aria-label="Release steps">
        {STEPS.map((s, i) => {
          const done = idx > i || (idx === 4);
          const now = idx === i;
          return <div role="listitem" key={s.id} class={`step${done ? " done" : ""}${now ? " now" : ""}`}><b>{done ? "[✓]" : now ? "[▸]" : "[ ]"} {s.name}</b><span>{s.hint(r)}</span></div>;
        })}
      </div>
      {r && ["skipped", "failed", "dry_run"].includes(r.stage) && <div class={`banner${r.stage === "failed" ? " bad" : ""}`}>Release {r.stage.replace("_", " ")}{r.dry_run_dir ? ` · ${r.dry_run_dir}` : ""}</div>}
      {r?.error && <div class="banner bad" role="alert">{r.error}</div>}
      <div class="grid2">
        <Pane label="release note preview">
          {!r ? <Empty>No release yet for this repository. Press c to cut one.</Empty> : (
            <div class="det">
              {editing.value ? <NoteEditor r={r} /> : r.note ? <pre class="note">{r.note}</pre> : <span class="dim">No note yet. Draft one with n once the release is merged.</span>}
              {posted ? <span class="c-o">Posted{r.note_permalink ? <> · <a href={r.note_permalink} target="_blank" rel="noopener noreferrer">open</a></> : ""}. Never retried.</span> : (
                <div class="acts">
                  <Btn k="p" primary disabled={!r.note} title={r.note ? undefined : "Draft a note first"} onClick={() => releaseOps.post()}>Post to #{settings.value?.release_note.channel_name ?? "channel"}</Btn>
                  <Btn k="e" disabled={!r.note} title={r.note ? undefined : "Draft a note first"} onClick={releaseOps.edit}>Edit</Btn>
                  <Btn k="x" bad onClick={() => releaseOps.skip()}>Skip</Btn>
                </div>
              )}
              <ActionBar actions={r.actions} />
            </div>
          )}
        </Pane>
        <Pane label="repositories">
          <div class="det">{repoList.value.map((x) => (
            <div key={x.repo} class="repo-row">
              <span><b>{x.name}</b> <span class="dim">· </span>{x.open ? <span class="c-q">release in flight</span> : x.ahead ? `${x.ahead} ahead · ${x.prs_waiting ?? "?"} PRs waiting` : <span class="dim">nothing new</span>}</span>
              {x.actions.length > 0 && <ActionBar actions={x.actions} />}
            </div>))}
            {repoList.value.length === 0 && <Empty>No repositories with a release branch.</Empty>}</div>
        </Pane>
      </div>
    </>
  );
}
