---
description: Create a GitHub issue with codebase context
argument-hint: "[bug | feature | task | improvement] <details | sentry-url | file-path | vault-note>"
---

> **Paths.** `<...>` placeholders below are keys from `aiw paths` (run it; `aiw` is
> on `PATH` via the plugin's `bin/`). Substitute the printed value; never guess a path.
I have a ${1:-bug / feature request / task / improvement} to log as a GitHub issue.

0. **Source check.** If `$@` matches one of `/intake`'s detectable source shapes — a
   `sentry.io` URL, an existing `.md`/`.txt`/`.pdf`/`.docx` file path, or a vault note
   title that exactly matches one note — invoke `/intake $@ --whole` and wait for its `## Intake
   result` block. Use its `type:` value in place of
   `${1:-bug / feature request / task / improvement}` for the rest of this skill, and use
   everything after its `---` line as `Details:` below. Otherwise (plain text, no source
   shape matched), skip this step — `/intake`'s own text adapter would be a no-op wrapper
   here, so there's no reason to make the extra call. When `/intake` was invoked, carry
   its brief's `Source:` line (in the brief's `## Notes` section) verbatim into the
   created issue's **Notes** section — it is traceability to the origin, not a claim
   about this repo, and must not be dropped or "corrected".

Details: $@

**HARD RULE — while executing steps 0–7 below, including everything under `4-FLAT`
(note: `4-FLAT` has its own internal 1–7 numbering; that's a sub-branch of top-level
step 4, not a separate range, and it is still fully bound by this rule), this skill only
ever creates a GitHub issue. It never touches code.**
- NEVER use Write, Edit, or NotebookEdit on any file in the repo.
- NEVER run a mutating shell command (`git commit`, `git checkout -b`, package installs, formatters, codemods, etc.).
- The ONLY writes permitted are the temp body file at `/tmp/gh-issue-body.md`, the `gh issue create` / `gh issue edit` / `gh project` calls below, and the notes-vault dump in step 7 (that's a different vault, not the repo, and goes through the `dump` skill's own confirmation).
- The sole exception to the rules above is the step 3.6 task-list save, and only when its conditions hold: (a) `docs/tasks/<slug>.md` written via the Write tool in step 3.6 and edited only to fill `Issue:` slots in `4-FLAT` (an override of the no-Write/no-Edit rule for that one path only); (b) the Obsidian `Tasks.md` via `obsidian vault=notes`, only when the user chose Obsidian, placed the way `/dump` does, plus the vault sibling writes `/dump`'s linking rules produce (the Index append and Related link); (c) the wiki clone/commit/push of `Tasks-<Title>.md` in a scratchpad clone, only when the user chose the wiki and confirmed the push (an override of the no-mutating-shell rule for that clone only). It covers nothing else: no other repo file, and no `git add` or commit of `docs/tasks/`.
- This holds even for a one-character fix. "It's trivial" is not an exception — the whole point of filing an issue is that a human decides whether and how to make the change.
- If a fix is obvious from your investigation, do NOT apply it. Record it under a **Proposed Fix** section in the issue body instead (file path, symbol, and the change in prose or a fenced diff).
- **Scope.** These constraints bind steps 0–7 of this skill only, including everything
  under `4-FLAT`. When `/run-issue` invoked this skill, they lapse the moment the issue
  URL is returned — the caller's later phases write code by design, and this rule must
  not be carried into them.

Do the following:

1. Use GitNexus MCP (`gitnexus_query`, `gitnexus_context`) to find the relevant code — execution flows, affected symbols, and files related to this description.
2. Check git status and recent commits for any in-progress work that touches the same area.
2.5. Dispatch the `run-researcher` agent (haiku, read-only) with the description above and the `owner/repo` slug, to collect context *outside* the codebase: prior related issues/PRs, project wiki, relevant public docs (library/API behavior the description implies). Carry its brief into steps 3 and 4 — do not print it verbatim, fold the relevant parts into the grilling and the issue body. Best-effort: if it errors or returns nothing useful, note that in one line and continue without it.
3. Use the grill-me skill to interview me on anything unclear (acceptance criteria, priority, affected users, edge cases), asking via the AskUserQuestion tool. Wait for my answers.
   - As part of this grilling session, enumerate every corner case you can find for this issue (empty/null input, concurrency, permissions, error/failure paths, boundary values, existing data migrations, etc.) and validate each one with me before moving on — don't assume a corner case is out of scope without asking.
3.5. **Decompose.** Every run, after step 3's grilling — no size test gates this, it
   always happens. Build a numbered task list from the grilled requirements. Each task
   has: a title, the one outcome it delivers, the files/symbols it's expected to touch
   (from step 1's GitNexus lookup), and `Depends on: task <k>` placeholder edges (using
   ordinals — the real issue numbers don't exist yet).

   Every task is one layer-scoped deliverable: a DB migration, service logic, an API
   endpoint (its request and resource count as one unit), or one UI unit. Each task
   touches 3 or fewer production files (tests not counted), has 1-4 acceptance
   criteria, has one verify command, and adds no new dependency. If an endpoint unit
   (controller, request, resource, routes) needs more than 3 production files, split it
   by file group (e.g. route+controller, then request+resource) rather than waiving the
   cap. Non-layered work (docs, config) uses the same limits, split by file or section. If any task fails the rubric,
   create nothing and don't ask yet: split the failing task and rebuild the list before
   presenting it.

   Present the list in exactly one `AskUserQuestion` call with two choices, verbatim:
   **"Create as shown"** and **"Let me edit the list"**.
   Style this like Gate 1's revise loop in `commands/run-issue.md`:

   - **"Let me edit the list"**: take the free-text feedback, revise the list, re-apply
     the rubric (a requested merge that would break a limit is declined, with the reason
     shown), and present the same question again. Loop until **"Create as shown"**
     is picked. No round limit.
   - **"Create as shown"**: route on the approved list's task count — 1 task goes to
     step 4 (single issue, unchanged); 2 or more tasks go to `4-FLAT`, in the list's dependency order, after step 3.6 saves the list.
3.6. **Save the task list.** Runs once, right after step 3.5's "Create as shown" and
   before its routing creates any issue. Slug: kebab-case from the PRD/source title (the
   `/intake` brief's title when step 0 ran). For free text with no title, propose a slug
   and have the user confirm it. Ask ONE `AskUserQuestion` (multiSelect) that shows the
   proposed slug as the recommended answer (the user edits it via Other) and offers the optional destinations Obsidian and/or GitHub wiki (local is always
   on, not a choice).

   If `docs/tasks/<slug>.md` already exists, stop and ask (new slug or skip the save); never
   overwrite silently.

   File shape: a header (title, source, date, owner/repo), then one block per task in the
   approved dependency order: `## Task <n> — <title>` (n is the task's sequence number),
   Outcome, Files/symbols, Acceptance criteria, Verify command, `Depends on: task <k>` (or
   none), and `Issue: —` (the issue-number slot, filled in later). Only when a task genuinely cannot be split further, and so still fails
   the size rubric, it gets a `Rubric: flagged — <limit broken>` line.

   - **Local** (always): write via the Write tool, creating `docs/tasks/` on demand. Never
     `git add` or commit it.
   - **Obsidian** (only if chosen): resolve `05-Work/<Project>/<Feature>/` the way `/dump`
     does (a new feature folder needs explicit OK). First run
     `obsidian vault=notes read path="05-Work/<Project>/<Feature>/Tasks.md"`; it prints
     `Error: ... not found` when missing. If the note exists, stop and ask (new name such
     as `Task List.md`, or skip Obsidian); never overwrite. Then
     `obsidian vault=notes create path="05-Work/<Project>/<Feature>/Tasks.md" ...`, tags via
     `property:set`, and a `## Related` append per `skills/dump/SKILL.md` "Tagging and
     linking". Never plain file writes.
   - **Wiki** (only if chosen): ask a separate "push the task list to the wiki?"
     confirmation. If yes, shallow-clone `.wiki.git` into the scratchpad, write
     `Tasks-<Title-With-Dashes>.md` (stop and ask if it exists), make a plain commit, and
     push. Never `--no-verify`. A repo with no wiki counts as a failed destination; do not
     create one.
   - **Failures**: an Obsidian or wiki failure keeps the local file. Report each
     destination on its own line with its path/URL, or `failed — <reason>` naming the
     destination by name, then continue. If the local write itself fails, stop before
     creating any issue.
4. Then create a GitHub issue on the current repo:
   - Write the full body to `/tmp/gh-issue-body.md` using the write tool
   - Every issue this command creates carries the `refined` label (unconditional). Ensure it
     exists once per run, before the first create (idempotent, cheap):
     ```bash
     gh label create refined --color 1D76DB --description "properly specified: passes the issue template" 2>/dev/null || true
     ```
   - Run `gh issue create --title "..." --label "refined,..." --body-file /tmp/gh-issue-body.md`
   - **NEVER use `--body` flag** — shell escaping breaks on backticks, pipes, quotes, newlines. Always `--body-file`.
   - Delete `/tmp/gh-issue-body.md` after the issue is created
   - Title: clear, specific, ≤72 chars
   - Body sections: **What** (the change: the business requirements, plus repro steps for a bug or requirements for a feature), **Why** (the problem and *why it matters* — not a restatement of the fix), **Out of Scope**, **Context / Affected Code** (file paths and symbols from step 1), **Acceptance Criteria** (include every corner case validated in step 3 as its own explicit criterion), **How** (ordered numbered steps; exact path:line/symbol references reusing the GitNexus lookup from step 1; an existing pattern to copy, or "no existing pattern — net-new"; the exact test/verify command(s); a one-line done-check), **Non-functional Constraints**, **Assumptions**, **Dependencies / Blockers**, **Proposed Fix** (only if a concrete fix is obvious — describe it, do NOT apply it), **Notes**
   - **These sections exist to clear `/run-issue`'s Gate 0.** `run-researcher` scores every issue against `<dor>` and *blocks the run* on a gap, so an issue filed without them gets bounced back to you with a `needs-info` comment. Read that file; it is six items and this section list is one-to-one with it.
     - **Out of Scope** — always at least one real entry. An issue with no stated edge is an issue whose PR grows one.
     - **Non-functional Constraints** — performance, security, authorization, data migration, backward compatibility. Write `none` deliberately where it's true; silence scores as unconsidered, `none` scores as answered.
     - **Assumptions** — anything you filled in that the issue's author didn't say, stated so they can correct it. This is the section that keeps a normalization from becoming invented scope.
     - **Dependencies / Blockers** — its own section, not a line in Notes. `none` beats silence here too.
     - Never delete one of these five to avoid writing `none`, and never ship a body containing `[bracketed placeholders]` — that is a failed run, not a draft.
   - **How is not a DoR item** — it's the plan, not a readiness gate.
     Required on every issue. Every step names a real path:line
     or symbol — no vague area names like "the auth code." A `[bracketed placeholder]`
     in it counts as a failed run under the same rule as the four sections above.
     When a **Proposed Fix** section is also present, it stays the literal patch;
     How is the ordered plan to get there.
   - Labels: bug / enhancement / feature / chore, plus scope labels (`backend`, `frontend`, `infra`) as applicable
   - **`lean` label.** `/run-issue` reads this label at init time to pick its roster
     without a human remembering to pass a flag — see `commands/run-issue.md`'s
     lean-mode tradeoff description. Apply `lean` only when **all** of these hold:
     - one independently-shippable outcome
     - roughly one to two files or symbols touched
     - no new dependency
     - no new public API surface
     - and **none** of: authentication/authorization, data migrations, payment paths,
       or a public API contract change
     Any doubt → no label. Full mode is the safe default.

     When `lean` is about to be applied, ensure it exists first (idempotent, cheap —
     only run this when the label is actually about to be applied, not on every issue):
     ```bash
     gh label create lean --color 0E8A16 --description "small, well-specified: run lean roster" 2>/dev/null || true
     ```

### 4-FLAT. Create the flat issues

One issue per task from the step 3.6 list, each standalone.

1. Ensure the labels once, before the first create (`<slug>` is the step 3.6 slug):

   ```bash
   gh label create refined --color 1D76DB --description "properly specified: passes the issue template" 2>/dev/null || true
   gh label create prd-<slug> --color 5319E7 --description "task from docs/tasks/<slug>.md" 2>/dev/null || true
   ```
2. Write one complete, DoR-passing body per task, using the same section list as step 4.
   Context is inlined, never referenced: a task body must stand alone. Each How covers
   only its own task. Notes links `Task <n> of docs/tasks/<slug>.md`.
3. Create the issues one at a time in list order. Before writing task k's body, replace
   each `Depends on: task <k>` line (k = an earlier task's number) with `Depends on: #<n>`, using the number already returned
   for that task (edges only point at earlier tasks). Write the body to
   `/tmp/gh-issue-body.md`, then run
   `gh issue create --title "..." --label "refined,prd-<slug>,<type>,<scope...>" --body-file /tmp/gh-issue-body.md`
   and delete the temp file. Labels are set at creation time: exactly `refined`,
   `prd-<slug>`, the type and the scope labels. `lean` is never applied here.
4. Write-back: right after each successful create, use the Edit tool to change that
   task's `Issue: —` line in `docs/tasks/<slug>.md` to `Issue: #<n>`. Skip the
   write-back when step 3.6 saved no local file.
5. Check each create's exit status. On failure, stop and report the created issues
   (number and URL) and the missing ones (planned title); never delete created issues.

4.5. Dispatch the `gh-issue-factchecker` agent (fresh context, no memory of the steps above) with just the issue number/URL and `owner/repo`. It re-reads the created issue cold and checks every concrete claim (file paths, symbols, described behavior, the proposed fix) against the real repo. Tell it explicitly: a `Source:` line in the Notes section pointing outside the repo (a Sentry permalink, an absolute file path, or a vault note path) is expected traceability from `/intake`, not a claim about this repo, and must not be flagged as an unverifiable claim.
   - `PASS` → continue to step 5, no mention needed.
   - `ISSUES FOUND` → fix the flagged text yourself, write the corrected body to `/tmp/gh-issue-body.md`, run `gh issue edit <n> --body-file /tmp/gh-issue-body.md`, delete the temp file, and briefly tell me what was wrong and corrected. Do not silently ignore a flagged discrepancy.
5. Assign the issue:
   - Get the default assignee: `gh api user --jq .login`.
   - Confirm via AskUserQuestion (`multiSelect: true`), with that login (as `@me`) recommended first, alongside other repo collaborators from `gh api repos/{owner}/{repo}/assignees --jq '.[].login'`.
   - Pass each chosen login as its own `--assignee <login>` flag on `gh issue create` (combine with the create call in step 4 rather than a separate call).
6. Add to a GitHub Project and fill its fields, discovered at runtime — never assume a project or field schema:
   - `gh project list --owner <repo-owner> --format json`
     - Zero projects → skip this step entirely, go straight to returning the URL.
     - One project → use it.
     - Multiple → ask via AskUserQuestion (`multiSelect: true`) which ones.
   - Add the issue to each chosen project at creation time, one `--project "<title>"` flag per project (same call as step 4/5).
   - For each chosen project, read its fields: `gh project field-list <number> --owner <owner> --format json`.
   - For each `ProjectV2SingleSelectField` on each project, ask the user to pick from that field's real `options` (never invent option names) — batch into as few AskUserQuestion calls as possible (max 4 questions per call). Skip any field the user declines to set.
   - Set each chosen field — **one field per `item-edit` call** (the CLI only supports single-field updates on non-draft issues):
     `gh project item-edit <number> --owner <owner> --url <issue-url> --field "<name>" --value "<option>"`
   - If any `gh project` call fails, don't abort — the issue already exists and is assigned. Report the URL and state plainly which fields couldn't be set and why (a missing `project` token scope is the likely cause; fix with `gh auth refresh -s project`).
   - Verify project fields landed with `gh issue view <n> --repo <owner>/<repo> --json projectItems` — cheap, and confirms per-project field values (e.g. Status) directly on the issue. Do NOT verify by paginating `gh project item-list` (projects can hold hundreds/thousands of items — pulling the full list to find one issue wastes time and burns context).
7. Dump the gathered context into the notes vault so it's there next time. Invoke the
   `ai-workflow:dump` skill, passing it: the issue title and URL, the final issue body, and the
   decisions from the step-3 grilling that did NOT make it into the body verbatim
   (rejected alternatives, corner cases ruled out and why, priority/scope calls). If
   step 2.5's research brief named a `feature folder`, state it as the proposed target so
   `/dump` doesn't re-derive it.

   `/dump` classifies, proposes a target, and confirms with you before writing — let it.
   Do not pre-empt or skip its confirmation.

   Best-effort: if the vault is unreachable or `/dump` is cancelled, say so in one line.
   The issue already exists and is the deliverable; the dump is not worth failing over.

Return the issue URL. If `/run-issue` invoked this skill, hand control back to its
Preflight step 3 with that issue number and continue the run; the HARD RULE above no
longer applies.
