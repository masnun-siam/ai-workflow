---
name: create-tasks
description: Break a PRD file into small, easy-to-verify tasks that several engineers can work on in parallel, then create every task as a child issue of the PRD's GitHub epic with native blocked-by links between them. Takes the PRD file path as its argument, or a finding (a bug or follow-up found during other work) to create a single issue for. Use when asked to break a PRD into tasks, create the issues for a PRD, or file an issue for something found mid-task.
argument-hint: <path to PRD file | finding>
---

# Create tasks

Input: the path to a PRD file, or a finding from other work (then follow "A finding from other work" below, not steps 1–11). Output: every task as a child issue of the PRD's GitHub epic, linked by GitHub's native blocked-by relationships so the order of work is clear. One PRD has one epic unless the PRD says otherwise. `/refine-issues` later writes the full WHAT/WHY/HOW into each issue; this skill creates them.

The PRD is the source of truth. This skill decides how the work is split, never what is built.

Paths below starting `../../` are relative to this skill's folder, at the plugin root. Read first: `../../guides/engineering-workflow.md` ("Repository settings", "Tasks" for the size and split rules, and "GitHub: project, epics and dependencies" for titles and labels).

## Steps

1. **Read the PRD** at the path given. If no path was given, ask for it. List every requirement and decision in it.

2. **Make sure the PRD answers everything** the split needs. For each gap or open question, ask the user with `AskUserQuestion`: recommended option first, with the reason. Write each answer into the PRD file, so the PRD stays the source of truth and nothing is decided mid-execution. Tell the user the PRD changed.

3. **Read the code the work touches**, with GitNexus or another code-graph tool when its index is available, and any repo documentation relevant to it, only to split the work well: which parts of the code each piece touches, and which files more than one piece would edit.

4. **Split into tasks.**
   - **Small.** Each task is a small chunk, one pull request with one outcome, so it is easy to verify. If you cannot state its outcome in one sentence, split it. Apply the size limits in the guide.
   - **Verifiable.** Each task says how to prove it is done.
   - **Parallel.** Several engineers work at once, so prefer independent tasks they can take at the same time, with as little conflict and overlap as possible. Avoid two parallel tasks editing the same file.
   - **Dependencies.** A task is blocked by another only when it cannot start without it. No cycles.
   - **Covered.** Every requirement in the PRD lands in a task, and no task adds anything the PRD does not ask for.

5. **Show the user the breakdown** before creating anything: each task's title, outcome, how to verify and what blocks it, and which tasks can start in parallel. Ask with `AskUserQuestion` whether to create the issues, adjust, or stop; recommended option first. Create nothing without a yes.

6. **Find the GitHub Project** from the projects existing issues in this repo are assigned to, by the rule in the guide. If they use more than one, ask which. If none, skip project steps and say so.

7. **Do not duplicate.** Find the epic `/create-prd` created on approval (the number in the PRD's "Epics" section, or the PRD path in an issue body). If child issues for this PRD already exist, update them instead of creating new ones.

8. **Create the epic only if it is missing**, from `../../templates/epic.md`, with the `epic` label, a body that says what the feature is and why, and the PRD path. Add it to the project and write its number into the PRD's "Epics" section.

9. **Create one child issue per task**, blockers first, with `gh issue create --parent <epic> --blocked-by <numbers>` and `--project <title>` when there is a project, titled and labelled as the guide says. Body: the outcome, how to verify, and the PRD path.

10. **Verify on GitHub** that every task is a child of the epic (`gh issue view <epic> --json subIssues`) and every blocked-by link matches the breakdown (`--json blockedBy`). Fix anything missing.

11. **Report and hand off.** Give the epic link and the issues, showing which can start now. The next step is `/refine-issues <epic number>`. Do not start it unless asked.

## A finding from other work

Input: what was found, where (file and line, command output), and the issue or pull request being worked on. Output: one issue, created here and then filled by `/refine-issues <n>`. Steps 1–11 do not apply.

1. **Do not duplicate.** Search open issues (`gh issue list --search`). If one already covers the finding, comment the new evidence there and hand that number to `/refine-issues` instead.
2. **Find its PRD**: the PRD of the epic or issue it came from, or one that covers the area. If none is found or linked, ask the user with `AskUserQuestion`, recommended option first: link an existing PRD, file a separate issue to create that PRD (through this section), or go on without one.
3. **Show the user** the title, the outcome in one sentence, the evidence, where it was found and its PRD, and ask with `AskUserQuestion` whether to create it; recommended option first. Create nothing without a yes.
4. **Create the issue** with `gh issue create`: a body with the finding, the evidence, a link to where it was found and the PRD path when there is one; the labels the guide lists for an issue (area, type, priority, and `prd-<slug>` when there is a PRD); `--parent <epic>` when it belongs to that epic; and the project found as in step 6. Comment its number on the issue it came from.
5. **Hand off.** The next step is `/refine-issues <new issue number>`, which writes the WHAT/WHY/HOW and adds the `refined` label.
