---
name: sync-from-wasensi
description: Keep this ai-workflow plugin in step with the Wasensi repo it was generalised from - compare Wasensi's merged skills, guides and templates with the plugin's, port every upstream change in repo-agnostic form, drop what is Wasensi-only, and commit after approval. Use whenever the user asks to sync, update, refresh or re-port the plugin from Wasensi, says Wasensi's skills or guides changed, or asks to "recheck wasensi and update the plugin".
argument-hint: "[path to the Wasensi repo]"
---

# Sync from Wasensi

The plugin's skills, guides and templates are a repo-agnostic port of Wasensi's. Wasensi keeps improving its copies, so this skill brings those improvements across without bringing Wasensi itself across: its stack, branch names, issue numbers or tooling.

Every run compares every file in full; there is no saved sync point that lets a file be skipped. That makes `references/generalisation-rules.md` the thing that separates a deliberate difference (already generalised, keep) from an upstream change (port). Read it before comparing anything.

Never edit the Wasensi repo; it is read-only input. All writes go to the plugin repo, the folder two levels above this skill (`../../`).

## Steps

1. **Find Wasensi.** Use the path given as the argument, else `~/Documents/Projects/BluBird/wasensi`. If neither is a git repo, ask the user for the path. Run `git -C <wasensi> fetch origin` and confirm `origin/staging` exists. Read upstream files from `origin/staging`, never from the working tree, so only merged work is ported. Note the `origin/staging` short sha for the commit message.

2. **Check the plugin is clean.** `git -C <plugin> status --short` must be empty. If it is not, show what is uncommitted and ask whether to continue; a sync commit must not sweep up unrelated edits. Run the leak scan from the rules file now too, as a baseline.

3. **Inventory both sides.** List upstream files with `git -C <wasensi> ls-tree -r --name-only origin/staging -- .claude/skills docs/guides docs/templates`, ignoring `.claude/skills/gitnexus/`. Map each to its plugin path with the table in the rules file. Sort every file into one of:
   - **Pair**: exists on both sides; compare it.
   - **New upstream**: has no plugin counterpart and is not in the rules file's "not ported" list.
   - **Gone upstream**: a plugin file whose upstream source no longer exists.
   - **Plugin-only**: listed as such in the rules file; only its skill tables are kept in step (step 5).

4. **Compare each pair in full.** Copy the upstream files into a scratch folder (`git show origin/staging:<path> > <scratch>/<path>`) so both sides can be read and diffed. Lines are whole paragraphs, so a plain `diff` shows little; `git diff --no-index --word-diff <upstream> <plugin>` shows the real changes. Then read both files completely: walk the upstream file statement by statement and ask whether it is in the plugin, verbatim or in its generalised form under the rules, then walk the plugin file and ask the reverse.

   To find recent changes fast, look at what Wasensi changed since the plugin's last sync: the sha in the latest `feat: sync with Wasensi <sha>` commit (`git -C <plugin> log --grep 'sync with Wasensi' -1`), then `git -C <wasensi> log --oneline <sha>..origin/staging -- <path>`. This is a starting point only; the full compare still decides, since an earlier sync may have missed something.

   Classify every difference:
   - **Already generalised**: a rule explains it. No action.
   - **Port**: upstream added, changed or removed something with generic value. Write the plugin version by applying the rules.
   - **Port, generalised**: a generic idea wrapped in Wasensi specifics (a make target, a stack tool, a port). Keep the idea, drop the specifics. If the idea holds only for some repos (a CI trigger, a hook behaviour), port it hedged ("if the repo...", "may") or drop it, and recommend one.
   - **Drop**: purely Wasensi (a stack command, an issue number, a trap only its tooling has).
   - **Unrecorded**: a difference in meaning that no rule explains, whether a plugin choice or something an earlier sync left out. Recommend keep or port, and record the answer as a rule (step 11), so the next run classifies it without asking. A rewording that says the same thing, or a Wasensi aside dropped because it adds nothing for other repos, is **Already generalised** without a rule; a rule per phrase would bury the ones that matter.
   - **Stale rule**: a rule that no longer matches the plugin or upstream (it names text that is gone, or the plugin rightly kept something the rule says was dropped). Propose the corrected rule.

   When Wasensi contradicts itself (a guide or template still says what its own skill no longer does), port from its skill, the source of truth, and list the contradiction in the report. It is not a reason to stop. When two Wasensi skills disagree, the skill that owns that stage wins (`/create-tasks` creates issues, `/refine-issues` fills them), and the disagreement goes in the report.

5. **Keep the plugin consistent.** Within the plugin the skill is the source of truth. After deciding the ports, check, and add a **Consistency fix** row for anything that breaks:
   - each guide and template still agrees with the skills;
   - every guide section a skill's "Read first" line names still exists under that name;
   - step numbers and cross-references resolve (for example "the points you log in step N");
   - the README stage table and the `guides/skills.md` skill table list every skill and describe it as the skill now does.

6. **Show the plan.** One row per change: file, upstream change in a few words, classification, and what the plugin will say. For a new section, give the full proposed text, not a summary. List new upstream files with a recommendation (port as generic, or skip as Wasensi-only), gone upstream files with a recommendation (remove, or keep because the plugin still needs it), the unrecorded differences with the rule you propose, and Wasensi's own contradictions. If nothing needs porting and no rule needs recording or correcting, say the plugin is in sync with that sha, list Wasensi's own contradictions, and stop. When `origin/staging` is the sha of the last sync, expect this; anything else found is an earlier miss. Otherwise ask with `AskUserQuestion` whether to apply all, adjust, or stop; recommended option first. Ask separately about each new or gone file. Write nothing without a yes.

7. **Apply.** Make the edits with exact replacements, not rewrites of whole files, so plugin-only wording survives. For a new upstream file, write the generalised version at its mapped path and add it to the skill tables.

8. **Verify.**
   - The leak scan in the rules file finds only its expected hits.
   - `claude plugin validate <plugin>` passes. Its note about a missing marketplace install line is expected; there is no marketplace on purpose.
   - Every `../../` path named in a skill exists, and every step and section reference resolves.

9. **Commit** in the plugin repo, on its own: `feat: sync with Wasensi <short sha> - <what changed>`, ending with the session's co-author line. Keep that subject shape: the next run finds its starting point by it. Do not push unless the user asks.

10. **Report** the Wasensi sha compared, the files changed, what was ported, what was generalised and how, what was dropped and why, the rules recorded, and every contradiction found inside Wasensi, without fixing it there.

11. **Record decisions.** Every answer about an unrecorded difference, and every new way of generalising something, goes into the rules file in the same commit.

## Stop and ask when

- `origin/staging` cannot be fetched (no network, no access).
- An upstream change contradicts a decision in the rules file (for example a Wasensi skill reintroduces a task-list file). Show both and ask which wins; record the answer.
- A change cannot be generalised without inventing a convention Wasensi does not have.
