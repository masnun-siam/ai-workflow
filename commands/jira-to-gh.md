---
description: Convert a Jira ticket to a GitHub issue
argument-hint: "<JIRA-KEY>"
---

> **Paths.** `<...>` placeholders below are keys from `aiw paths` (run it; `aiw` is
> on `PATH` via the plugin's `bin/`). Substitute the printed value; never guess a path.

Convert Jira ticket $1 to a GitHub issue.

## Step 1 — Fetch Jira ticket

Run this command to get all ticket data in one shot:

```bash
acli jira workitem view $1 --fields '*all' --json
```

Parse the JSON output. Extract:

- Summary / title
- Description (full body)
- Issue type (bug, story, task, epic)
- Priority
- Labels
- Components
- Acceptance criteria (if present in description or custom fields)
- Linked issues / parent epic
- Reporter and assignee
- **Attachments** — list of attachment objects with `filename`, `content` (download URL), `mimeType`, `size`

## Step 2 — Download Jira attachments

If the ticket has attachments in the JSON output (`attachment` field):

1. Create a temp directory:

   ```bash
   TMPDIR=$(mktemp -d)
   ```

2. Download each attachment:

   ```bash
   curl -sL -o "$TMPDIR/<filename>" "<attachment.content_url>"
   ```

   If the Jira instance requires auth, use the credentials from `acli` config or pass `-u email:token`.

3. Keep the file list for Step 6.

## Step 3 — Map to GitHub issue

Translate Jira fields to GitHub format:

- **Title**: Use summary, ≤72 chars, specific and actionable
- **Body sections**:
  - **What** — the business requirements, plus repro steps for a bug or requirements for a feature, extracted from the description (or "To be defined")
  - **Why** — from Jira description: the problem and why it matters
  - **Original Jira** — link back: `$1` (include Jira URL if determinable from config)
  - **Acceptance Criteria** — from description or custom fields
  - **Notes** — priority, linked issues, any extra context
- **Labels**: Map Jira issue type → `bug`/`enhancement`/`feature`/`chore`. Add scope labels from components if applicable.
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
- **On the multi-task path** (Step 4.5 routes to `5-FLAT`), this mapping seeds the
  task list, and each task's issue inlines the Jira context from it. `lean` is never applied
  there.

## Step 4 — Ask clarifying questions

Ask me up to 3 focused questions if anything is unclear or missing (e.g., acceptance criteria, priority override, scope labels). Wait for my answers.

## Step 4.5 — Decompose

Every run, after Step 4's clarifying questions — no size test gates this, it always
happens. Use GitNexus MCP (`gitnexus_query`, `gitnexus_context`) to find the relevant
code — execution flows, affected symbols, and files related to the ticket —
each task's issue needs this for its Context / Affected Code and How
path:line references.

Build a numbered task list seeded from Step 3's field mapping (summary, description,
acceptance criteria, linked issues) plus Step 4's clarifying answers — not from a
grilling transcript; jira-to-gh has no grilling step, and Step 4's Q&A already serves
that role. Each task has: a title, the one outcome it delivers, the files/symbols it's
expected to touch, and `Depends on: task <k>` placeholder edges (using ordinals — the
real issue numbers don't exist yet).

Every task is one layer-scoped deliverable: a DB migration, service logic, an API
endpoint (its request and resource count as one unit), or one UI unit. Each task
touches 3 or fewer production files (tests not counted), has 1-4 acceptance
criteria, has one verify command, and adds no new dependency. If an endpoint unit
(controller, request, resource, routes) needs more than 3 production files, split it
by file group (e.g. route+controller, then request+resource) rather than waiving the
cap. Non-layered work (docs, config) uses the same limits, split by file or section. If any task fails the rubric,
create nothing and don't ask yet: split the failing task and rebuild the list before presenting it.

Present the list in exactly one `AskUserQuestion` call with two choices, verbatim:
**"Create as shown"** and **"Let me edit the list"**.
Style this like Gate 1's revise loop in `commands/run-issue.md`:

- **"Let me edit the list"**: take the free-text feedback, revise the list, re-apply
  the rubric (a requested merge that would break a limit is declined, with the reason
  shown), and present the same question again. Loop until **"Create as shown"**
  is picked. No round limit.
- **"Create as shown"**: route on the approved list's task count — 1 task goes to Step 5 (single-task path); 2 or more tasks go to `5-FLAT`, in the list's dependency order, after Step 4.6 saves the list.

## Step 4.6 — Save the task list

Runs once, right after Step 4.5's "Create as shown" and before its routing creates any issue. Slug: kebab-case from the Jira ticket's summary (Step 3's title).

This step is skipped when exactly 1 task was approved: Step 5 files it as a single issue and no task list is saved.

Ask ONE `AskUserQuestion` (multiSelect) that shows the
proposed slug as the recommended answer (the user edits it via Other) and offers the optional destinations Obsidian and/or GitHub wiki (local is always
on, not a choice).

If `docs/tasks/<slug>.md` already exists, stop and ask (new slug, skip the save, or **"Resume this list"**); never
overwrite silently. Show the existing file's title, source and how many `Issue:` slots are filled, so the user can tell a resume from an unrelated collision. **"Resume this list"** leaves the file as is and goes to `5-FLAT`, which then uses the saved list instead of the one just approved. Resume skips the Obsidian/wiki destination writes: the saved list is only read, not rewritten.

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

Remove any temp files this skill created before stopping.

## Step 5 — Create GitHub issue (single-task path)

This step runs only when exactly 1 task was approved in Step 4.5.

Write the full body to `/tmp/gh-issue-body.md` using the write tool. Every issue carries
the `refined` label (unconditional); ensure it exists first (idempotent, cheap):

```bash
gh label create refined --color 1D76DB --description "properly specified: passes the issue template" 2>/dev/null || true
```

If `lean` is one of the labels being applied, ensure the label exists first (idempotent, cheap — only run
this when the label is actually about to be applied, not on every issue):

```bash
gh label create lean --color 0E8A16 --description "small, well-specified: run lean roster" 2>/dev/null || true
```

Then run:

```bash
gh issue create --title "TITLE" --label "refined,labels" --body-file /tmp/gh-issue-body.md
```

**NEVER use `--body` flag** — shell escaping breaks on backticks, pipes, quotes, newlines. Always `--body-file`.

### 5-FLAT. Create the flat issues

This section runs only when Step 4.5 routed 2 or more tasks here — it is an alternate path to Step 5 above, not a sub-case nested under it.

One issue per task from the Step 4.6 list, each standalone.

0. Preflight, before anything is created. If Step 4.6 skipped the save because
   `docs/tasks/<slug>.md` already exists, stop and ask for a new slug by Step 4.6's
   existing rule, so the `prd-<slug>` label and Notes links never mix two lists. Then check
   every `Depends on: task <j>` in task k has j < k; otherwise stop, report the offending
   task, and let the user fix the list via Step 4.5's edit loop.
   This resume branch overrides the new-slug stop above: choosing **"Resume this list"** is not skipping the save, and the `j < k` check runs on the saved list (the one Resume uses), not the approved one it discards.
   If the user chose **"Resume this list"** in Step 4.6, the saved `docs/tasks/<slug>.md` is the list: read it, show which tasks have no issue number yet, and create only tasks without an issue number, in list order; reuse the existing `Issue: #<n>` numbers for their `Depends on:` lines. First run `gh issue list --label prd-<slug> --state all --limit 200 --json number,url,title,body` (the guard runs before the show step is final, so that list reflects its findings); an issue whose Notes says `Task <n> of docs/tasks/<slug>.md` (Notes wrap the path in backticks, so match on the `Task <n> of` text and the slug) for a task with an empty slot, and whose title also matches that task's planned title, was created but never recorded, so fill that slot with the sub-step 4 write-back instead of creating it again. A Notes-only match with a different title may belong to another list sharing the slug: report it and leave it for the user. If every slot is filled, create nothing and report the existing issues.
1. Ensure the labels once, before the first create (`<slug>` is the Step 4.6 slug):

   ```bash
   gh label create refined --color 1D76DB --description "properly specified: passes the issue template" 2>/dev/null || true
   gh label create prd-<slug> --color 5319E7 --description "task from docs/tasks/<slug>.md" 2>/dev/null || true
   ```
2. Write one complete, DoR-passing body per task, with Jira context from Step 3 inlined.
   Context is inlined, never referenced: a task body must stand alone. Each How covers
   only its own task. Notes links `Task <n> of docs/tasks/<slug>.md`.
   - Body sections: **What** (the change: the business requirements, plus repro steps for a bug or requirements for a feature), **Why** (the problem and *why it matters* — not a restatement of the fix), **Out of Scope**, **Context / Affected Code** (file paths and symbols from Step 4.5's GitNexus lookup), **Acceptance Criteria** (include every corner case surfaced in Step 4's clarifying Q&A as its own explicit criterion), **How** (ordered numbered steps; exact path:line/symbol references reusing the GitNexus lookup from Step 4.5; an existing pattern to copy, or "no existing pattern — net-new"; the exact test/verify command(s); a one-line done-check), **Non-functional Constraints**, **Assumptions**, **Dependencies / Blockers**, **Proposed Fix** (only if a concrete fix is obvious — describe it, do NOT apply it), **Notes** (include the Jira key/URL here as traceability)
3. Create the issues one at a time in list order. Before writing task k's body, replace
   each `Depends on: task <k>` line (k = an earlier task's number) with `Depends on: #<n>`, using the number already returned
   for that task (or already in its `Issue:` slot) (edges only point at earlier tasks). Write the body to
   `/tmp/gh-issue-body.md`, then run
   `gh issue create --title "..." --label "refined,prd-<slug>,<type>,<scope...>" --body-file /tmp/gh-issue-body.md`
   and delete the temp file. Labels are set at creation time: exactly `refined`,
   `prd-<slug>`, the type and the scope labels. `lean` is never applied here.
4. Write-back: every task block ends with an identical `Issue: —` line, so never
   `replace_all` and never Edit on that line alone. Right after each successful create,
   Edit with an `old_string` that starts at the task's own `## Task <k> — <title>` heading
   and runs through its `Issue: —` line (unique), setting `Issue: #<n>`. Skip when
   Step 4.6 saved no local file.
5. Check each create's and each write-back's exit status. On failure, stop like a failed
   create: report the created issues (number and URL), the missing ones (by planned title),
   and any issue that exists but is unrecorded in the file; never delete created issues.
   Then `AskUserQuestion` with exactly these two choices: **"Retry the missing ones"**, **"Stop here"**.
   - **"Retry the missing ones"**: re-enter the loop at the failed task, reusing the already-known issue numbers of earlier tasks for their `Depends on:` lines; never re-create a task that already has an issue (an unrecorded one gets its write-back retried, not a second create). Apply the duplicate guard above before every create after a failure: run the same `gh issue list --label prd-<slug> --state all --limit 200 --json number,url,title,body` lookup, so an issue GitHub accepted but whose create reported no number is recorded, not created twice.
   - **"Stop here"**: first run Step 6's attachment upload against the issues created so far (skip it if none were created), then Step 7's cleanup, then end the run and report the partial state (created vs. missing); the filled `Issue:` slots let a later run resume the list.
   Never close or delete an issue already created — a partial list is a recoverable state.
6. Dispatch the `gh-issue-factchecker` agent (fresh context, no memory of the steps above) once per issue in the ordered list this run returns (created now or reused on resume), each time with just that issue's number/URL and `owner/repo`. It re-reads the created issue cold and checks every concrete claim (file paths, symbols, described behavior, the proposed fix) against the real repo. Tell it explicitly: a Jira key/URL in the **Notes** section is expected traceability from `$1`, not a claim about this repo, and must not be flagged as an unverifiable claim.
   - `PASS` → continue, no mention needed.
   - `ISSUES FOUND` → fix the flagged text yourself, write the corrected body to `/tmp/gh-issue-body.md`, run `gh issue edit <n> --body-file /tmp/gh-issue-body.md`, delete the temp file, and briefly say what was wrong and corrected.
7. Assignees and project-board questions from `commands/gh-issue.md`'s flat flow (`4-FLAT`) are deliberately NOT mirrored here, since jira-to-gh has neither today — this is a scope choice, not an oversight.
8. Delete `/tmp/gh-issue-body.md` after the last create/edit.

## Step 6 — Upload attachments to GitHub issue

If attachments were downloaded in Step 2, post each as a comment on `<TARGET_ISSUE>` —
Step 5's created issue number on the single-task path, or each issue created by `5-FLAT`
on the multi-task path (every issue created in this run, not re-attached on resume).

**For images** (png, jpg, gif, webp) — embed as base64 in markdown (works for small images <64KB):

```bash
BASE64=$(base64 -i "$TMPDIR/<filename>")
gh issue comment <TARGET_ISSUE> --repo <OWNER/REPO> \
  --body "### 📎 Attachment: <filename>

![<filename>](data:<mime_type>;base64,$BASE64)"
```

If base64 is too large (>64KB), fall back to noting the file:

```bash
SIZE=$(stat -f%z "$TMPDIR/<filename>" 2>/dev/null || stat -c%s "$TMPDIR/<filename>")
gh issue comment <TARGET_ISSUE> --repo <OWNER/REPO> \
  --body "### 📎 Attachment: <filename>

**<filename>** (${SIZE} bytes, <mime_type>)
Downloaded from Jira ticket $1. See original ticket for the file."
```

**For non-image files** (docs, zips, etc.) — note the attachment with metadata:

```bash
SIZE=$(stat -f%z "$TMPDIR/<filename>" 2>/dev/null || stat -c%s "$TMPDIR/<filename>")
gh issue comment <TARGET_ISSUE> --repo <OWNER/REPO> \
  --body "### 📎 Attachment: <filename>

**<filename>** (${SIZE} bytes, <mime_type>)
Downloaded from Jira ticket $1 — see original Jira ticket to download the file directly."
```

Note: GitHub issue comments don't support arbitrary file uploads. For images, base64 embedding works for small files. For everything else, link back to the Jira ticket for download.

## Step 7 — Cleanup

```bash
[ -n "$TMPDIR" ] && rm -rf "$TMPDIR"
```

Return the issue URL and list of uploaded attachments when done on the single-task
path. On the multi-task path, return the ordered list of issue URLs, one per task in list order (including issues reused on resume), plus the list of uploaded attachments.
