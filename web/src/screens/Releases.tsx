import { computed, signal } from "@preact/signals";
import { useEffect, useState } from "preact/hooks";
import { http } from "../api/http";
import type { Release, ReleaseStage } from "../api/types";
import { currentRepo, loadErrors, mutate, releases, settings } from "../state/data";
import { askConfirm, toast } from "../state/ui";
import { ago } from "../state/format";
import { Header } from "../components/Header";
import { ActionBar } from "../components/ActionBar";
import { Btn, Empty, Pane } from "../components/ui";
import { Select } from "../components/Select";

/** The repository picked on this page; it applies only while the current repo is the one it was picked under. ALL_REPOS shows every release. */
const ALL_REPOS = "*";
const relRepo = signal<{ under: string | null; repo: string } | null>(null);
const editing = signal(false);
const DONE = new Set<ReleaseStage>(["done", "skipped", "failed"]);

const repoList = computed(() => releases.value?.repos ?? []);
const busyRepo = (r: { open: string | null; ahead: number | null }) => !!r.open || (r.ahead ?? 0) > 0;
/** Repos with a release in flight or commits ahead come first (the sort is stable). */
const sortedRepos = computed(() => [...repoList.value].sort((a, b) => Number(busyRepo(b)) - Number(busyRepo(a))));
const has = (slug: string | null | undefined): slug is string => !!slug && repoList.value.some((r) => r.repo === slug);
const allRepos = computed(() => relRepo.value?.under === currentRepo.value && relRepo.value?.repo === ALL_REPOS);
const repoSlug = computed(() => {
  if (allRepos.value) return null;
  const picked = relRepo.value?.under === currentRepo.value ? relRepo.value?.repo : null;
  if (has(picked)) return picked;
  if (has(currentRepo.value)) return currentRepo.value;
  return sortedRepos.value[0]?.repo ?? null;
});
/** The release in flight for the repo (every repo under "All repos"), else the newest one. */
export const currentRelease = computed<Release | null>(() => {
  const all = (releases.value?.releases ?? []).filter((r) => !repoSlug.value || r.repo === repoSlug.value);
  return all.find((r) => !DONE.has(r.stage)) ?? all[0] ?? null;
});

const KEYS = ["releases"] as const;
const NO_RELEASE = "No release yet";
const noteBlock = (r: Release | null): string | null => (!r ? NO_RELEASE : r.note_posted_at ? "The note is already posted" : null);
/** Why an action is blocked right now, or null. The keys and the buttons share these, so the toast and the button's title agree. */
export const releaseBlock = {
  cut: (): string | null => {
    const repo = repoList.value.find((x) => x.repo === repoSlug.value);
    return !repo ? (allRepos.value ? "Pick a repository first" : "No repository with releases") : repo.open ? "A release is already in flight for this repository" : null;
  },
  grind: (): string | null => (currentRelease.value ? null : NO_RELEASE),
  note: (): string | null => noteBlock(currentRelease.value),
  post: (): string | null => { const r = currentRelease.value; return noteBlock(r) ?? (r?.note ? null : "Draft a note first"); },
  edit: (): string | null => { const r = currentRelease.value; return noteBlock(r) ?? (r?.note ? null : "Draft a note first"); },
  skip: (): string | null => (currentRelease.value ? null : NO_RELEASE),
};
/** True (after a warning toast) when the action is blocked. */
const refused = (why: string | null): boolean => { if (why) toast(why, "warn"); return !!why; };
export const releaseOps = {
  cut: async (dry: boolean) => {
    const repo = repoSlug.value;
    if (refused(releaseBlock.cut()) || !repo) return;
    if (!dry && !(await askConfirm(`Cut a release of ${repo}?`))) return;
    return mutate(() => http.send("POST", "/api/releases", { repo, dry_run: dry || undefined }), dry ? "Dry run started" : "Started release-pr", [...KEYS, "river"]);
  },
  grind: () => { const r = currentRelease.value; return !refused(releaseBlock.grind()) && r ? mutate(() => http.send("POST", `/api/releases/${r.id}/grind`, {}), "Grind started", [...KEYS]) : undefined; },
  note: () => { const r = currentRelease.value; return !refused(releaseBlock.note()) && r ? mutate(() => http.send("POST", `/api/releases/${r.id}/note`, {}), "Drafting the note", [...KEYS]) : undefined; },
  skip: async () => { const r = currentRelease.value; if (!refused(releaseBlock.skip()) && r && (await askConfirm("Skip this release?"))) await mutate(() => http.send("POST", `/api/releases/${r.id}/skip`, {}), "Skipped", [...KEYS, "river"]); },
  post: async () => {
    const r = currentRelease.value; if (refused(releaseBlock.post()) || !r) return;
    const ch = settings.value?.release_note.channel_name ?? "the channel";
    if (await askConfirm(`Post the note to #${ch}? It posts once and is never retried.`)) await mutate(() => http.send("POST", `/api/releases/${r.id}/post`, {}), `Posted to #${ch}`, [...KEYS, "river", "inbox"]);
  },
  edit: () => { if (!refused(releaseBlock.edit())) editing.value = true; },
};
/** Screen keys c y G n p e x (G, not g: `g` starts the go-to chord). Returns true when handled. */
export function releaseKey(k: string): boolean {
  const map: Record<string, () => unknown> = { c: () => releaseOps.cut(false), y: () => releaseOps.cut(true), G: releaseOps.grind, n: releaseOps.note, p: releaseOps.post, e: releaseOps.edit, x: releaseOps.skip };
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
  const cutBlocked = releaseBlock.cut();
  const cutWhy = cutBlocked ?? "Open a release PR";
  const postBlocked = releaseBlock.post();
  const editBlocked = releaseBlock.edit();
  return (
    <>
      <Header title="Releases" products>
        <Btn k="c" onClick={() => releaseOps.cut(false)} disabled={!!cutBlocked} title={cutWhy}>Cut release</Btn>
        <Btn k="y" onClick={() => releaseOps.cut(true)} disabled={!!cutBlocked} title={cutWhy}>Dry run</Btn>
        <Btn k="G" onClick={() => releaseOps.grind()} disabled={!!releaseBlock.grind()} title={releaseBlock.grind() ?? "Grind the release PR"}>Grind</Btn>
        <Btn k="n" onClick={() => releaseOps.note()} disabled={!!releaseBlock.note()} title={releaseBlock.note() ?? "Draft the release note"}>Note</Btn>
      </Header>
      {err && <div class="banner bad" role="alert">{err}</div>}
      {repoList.value.length > 0 && <Select label="Repository" value={repoSlug.value ?? ALL_REPOS}
        options={[...sortedRepos.value.map((x) => ({ value: x.repo, label: x.name, hint: x.open ? "in flight" : x.ahead ? `${x.ahead} ahead` : undefined })), { value: ALL_REPOS, label: "All repos" }]}
        onChange={(v) => { relRepo.value = { under: currentRepo.value, repo: v }; editing.value = false; }} />}
      {repo && <span class="mu">{repo.repo} · {repo.head} → {repo.base}{repo.last_release ? ` · last #${repo.last_release.pr} ${ago(repo.last_release.merged_at)}` : ""}</span>}
      <div class="steps" role="list" aria-label="Release steps">
        {STEPS.map((s, i) => {
          const done = idx > i || (idx === 4);
          const now = idx === i;
          return <div role="listitem" key={s.id} aria-current={now ? "step" : undefined} class={`step${done ? " done" : ""}${now ? " now" : ""}`}><b><span aria-hidden="true">{done ? "[✓]" : now ? "[▸]" : "[ ]"}</span> {s.name}{done && <span class="sr"> (done)</span>}</b><span>{s.hint(r)}</span></div>;
        })}
      </div>
      {r && ["skipped", "failed", "dry_run"].includes(r.stage) && <div class={`banner${r.stage === "failed" ? " bad" : ""}`}>Release {r.stage.replace("_", " ")}{r.dry_run_dir ? ` · ${r.dry_run_dir}` : ""}</div>}
      {r?.error && <div class="banner bad" role="alert">{r.error}</div>}
      <div class="grid2">
        <Pane label="release note preview">
          {!r ? <Empty>{`No release yet for this repository.${cutBlocked ? "" : " Press c to cut one."}`}</Empty> : (
            <div class="det">
              {editing.value ? <NoteEditor r={r} /> : r.note ? <pre class="note">{r.note}</pre> : <span class="dim">No note yet. Draft one with n once the release is merged.</span>}
              {posted ? <span class="c-o">Posted{r.note_permalink ? <> · <a href={r.note_permalink} target="_blank" rel="noopener noreferrer">open</a></> : ""}. Never retried.</span> : (
                <div class="acts">
                  <Btn k="p" primary disabled={!!postBlocked} title={postBlocked ?? undefined} onClick={() => releaseOps.post()}>Post to #{settings.value?.release_note.channel_name ?? "channel"}</Btn>
                  <Btn k="e" disabled={!!editBlocked} title={editBlocked ?? undefined} onClick={releaseOps.edit}>Edit</Btn>
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
              {x.actions.length > 0 && <ActionBar actions={x.actions} showKey={(a) => x.repo === repoSlug.value && a.key === "c"} primary={(a) => x.repo === repoSlug.value && a.key === "c"} />}
            </div>))}
            {repoList.value.length === 0 && <Empty>No repositories with a release branch.</Empty>}</div>
        </Pane>
      </div>
    </>
  );
}
