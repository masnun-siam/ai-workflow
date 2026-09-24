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
  - **Summary** — from Jira description
  - **Specific Business Requirements** — extracted acceptance criteria or "To be defined"
  - **Original Jira** — link back: `$1` (include Jira URL if determinable from config)
  - **Steps to Reproduce / Requirements** — from description
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
- **On the multi-task path** (Step 4.5 routes to Step 5-EPIC), this mapping becomes
  the **parent's** body instead of a single issue's body, and `lean` is never judged
  here — it is judged per child in Step 5-EPIC, against each child's own body, never
  on the parent.

## Step 4 — Ask clarifying questions

Ask me up to 3 focused questions if anything is unclear or missing (e.g., acceptance criteria, priority override, scope labels). Wait for my answers.

## Step 4.5 — Decompose

Every run, after Step 4's clarifying questions — no size test gates this, it always
happens. Use GitNexus MCP (`gitnexus_query`, `gitnexus_context`) to find the relevant
code — execution flows, affected symbols, and files related to the ticket — the
children need this for their Context/Affected Code and Implementation Guide
path:line references.

Build a numbered task list seeded from Step 3's field mapping (summary, description,
acceptance criteria, linked issues) plus Step 4's clarifying answers — not from a
grilling transcript; jira-to-gh has no grilling step, and Step 4's Q&A already serves
that role. Each task has: a title, the one outcome it delivers, the files/symbols it's
expected to touch, and `Depends on: task <k>` placeholder edges (using ordinals — the
real issue numbers don't exist yet).

More than ~8 tasks is a decomposition problem, not a bigger epic: create nothing and
don't ask yet — say so, then rebuild the list coarser once before presenting it.

Present the list in exactly one `AskUserQuestion` call with three choices, verbatim:
**"Create as shown"**, **"Let me edit the list"**, **"File as one issue instead"**.

- **"Let me edit the list"**: take the free-text feedback, revise the list, re-apply
  the more-than-8 guard, and present the same question again. Loop until one of the
  other two choices is picked. No round limit.
- **"Create as shown"**: route on the approved list's task count, not on the choice
  itself — 1 task goes to Step 5 (single, below); 2 or more tasks go to Step 5-EPIC,
  in the list's dependency order.
- **"File as one issue instead"**: go to Step 5 with the full Step 3 mapping,
  bypassing Step 5-EPIC entirely, regardless of how many tasks were on the list.

## Step 5 — Create GitHub issue (single-task path)

This step runs only when exactly 1 task was approved in Step 4.5, or "File as one
issue instead" was chosen.

Write the full body to `/tmp/gh-issue-body.md` using the write tool. If `lean` is one of
the labels being applied, ensure the label exists first (idempotent, cheap — only run
this when the label is actually about to be applied, not on every issue):

```bash
gh label create lean --color 0E8A16 --description "small, well-specified: run lean roster" 2>/dev/null || true
```

Then run:

```bash
gh issue create --title "TITLE" --label "labels" --body-file /tmp/gh-issue-body.md
```

**NEVER use `--body` flag** — shell escaping breaks on backticks, pipes, quotes, newlines. Always `--body-file`.

### 5-EPIC. Create the parent and its children

This section runs only when Step 4.5 routed 2 or more tasks here — it is an
alternate path to Step 5 above, not a sub-case nested under it.

1. Create the **parent** with Step 3's field mapping as its body — Step 3's mapping
   already includes an `## Original Jira` section linking back to `$1`; reuse it,
   don't add a second one. Labels: `epic` plus the Jira-mapped type labels from Step 3 — it is
   **never** labelled `lean`, a container spans however many children it has. It
   needs no Implementation Guide (parent exemption). Ensure the `epic` label exists
   first (idempotent, cheap):
   ```bash
   gh label create epic --color 5319E7 --description "parent of a decomposed issue" 2>/dev/null || true
   ```
2. Create children one at a time, in the approved list's dependency order. Each
   child gets a **complete, independently DoR-satisfying** body — full context
   written out, never "see parent" — with the parent's Jira context inlined.

   - Body sections: **Summary** (the problem and *why it matters* — not a restatement of the fix), **Specific Business Requirements**, **Out of Scope**, **Context / Affected Code** (file paths and symbols from Step 4.5's GitNexus lookup), **Steps to Reproduce / Requirements**, **Acceptance Criteria** (include every corner case surfaced in Step 4's clarifying Q&A as its own explicit criterion), **Implementation Guide** (ordered numbered steps; exact path:line/symbol references reusing the GitNexus lookup from Step 4.5; an existing pattern to copy, or "no existing pattern — net-new"; the exact test/verify command(s); a one-line done-check), **Non-functional Constraints**, **Assumptions**, **Dependencies / Blockers**, **Proposed Fix** (only if a concrete fix is obvious — describe it, do NOT apply it), **Notes** (include the Jira key/URL here as traceability)
   - Each child is one **vertical slice** — one thin end-to-end outcome, never a
     layer. Each child's Implementation Guide covers only that child's own slice —
     never a step that touches a sibling's files or refers to a sibling's steps.
   - Before writing child k's body, replace each `task <j>` placeholder from Step
     4.5's list with the real `#<n>` issue number already returned for child j
     (child j must have been created first).
   - Where a child depends on a sibling, add a line on its own:
     ```
     Depends on: #<n>, #<n>
     ```
     Edges may only point at siblings in this epic.
   - Include `epic-<parent>` in each child's `--label` list on its `gh issue create`
     call, alongside its normal labels — apply it at creation time, not afterward, so
     every child already created is immediately findable via
     `gh issue list --label epic-<parent>` regardless of where the loop stopped. When
     `epic-<parent>` is about to be applied for the first time this run, ensure it
     exists first (idempotent, cheap):
     ```bash
     gh label create epic-<parent> --color 5319E7 --description "child of epic #<parent>" 2>/dev/null || true
     ```
   - Judge each child against Step 3's `lean` heuristic **independently, against its
     own body** — a child's own outcome, file count, dependency, API-surface and
     risk-area answers, not the epic's aggregate. The same idempotent ensure-create
     runs once, before the first child that earns the `lean` label:
     ```bash
     gh label create lean --color 0E8A16 --description "small, well-specified: run lean roster" 2>/dev/null || true
     ```

   Check each `gh issue create` exit status immediately. On failure at child k of N
   (k=0 means the parent itself failed, before any children exist): stop the loop.
   Report, by number, which issues exist (the parent and children 1..k-1, with the
   URLs already returned by their create calls) and which are missing (k..N, by
   planned title).

   Then `AskUserQuestion` with exactly these two choices: **"Retry the missing ones"**,
   **"Stop here"**.

   - **"Retry the missing ones"**: re-enter the loop starting at child k, reusing the
     already-known issue numbers for children 1..k-1 (needed for their `Depends on:`
     lines in later children). Never re-create 1..k-1.
   - **"Stop here"**: before ending the run — if the parent was successfully created
     (k > 0), still run Step 6's attachment upload against the parent (attachments
     describe the whole Jira ticket, which exists regardless of how many children got
     created); if the parent itself failed (k=0), skip Step 6, there is nothing to
     attach to. Either way, run Step 7's cleanup. Then end the run, report the partial
     state (created vs. missing), do NOT call `aiw epic split` (it only runs once every
     planned child exists), and return no issue URL/number.

   Never auto-close or delete issues already created — a partial epic is a
   recoverable state, not a failure state.
3. Link and validate. This step only runs once every planned child exists — step 2's
   partial-failure gating is what guarantees that:

   ```bash
   aiw epic split "<runs_dir>/<owner>-<repo>-epic-<parent>" \
     --parent <parent> --slug <owner>/<repo> --children <n>,<n>,<n>
   ```

   Exit 1 means the edges do not form a DAG — a cycle, a self-edge, or an edge pointing
   outside the epic. Fix the offending child's `Depends on:` line with `gh issue edit`
   and re-run. Do not proceed with an invalid DAG.
4. Dispatch the `gh-issue-factchecker` agent once per child, never on the parent —
   each child body makes its own concrete claims about files and symbols, which is
   exactly what the factchecker verifies; a check against the parent would miss them.
   Tell it explicitly: a Jira key/URL in the **Notes** section is expected
   traceability from `$1`, not a claim about this repo, and must not be flagged as an
   unverifiable claim.
   - `PASS` → continue, no mention needed.
   - `ISSUES FOUND` → fix the flagged text yourself, write the corrected body to
     `/tmp/gh-issue-body.md`, run `gh issue edit <n> --body-file /tmp/gh-issue-body.md`,
     delete the temp file, and briefly say what was wrong and corrected.
5. Assignees and project-board steps from `commands/gh-issue.md`'s 4-EPIC are
   deliberately NOT mirrored here, since jira-to-gh has neither today — this is a
   scope choice, not an oversight.
6. Delete `/tmp/gh-issue-body.md` after the last create/edit.

## Step 6 — Upload attachments to GitHub issue

If attachments were downloaded in Step 2, post each as a comment on `<TARGET_ISSUE>` —
Step 5's created issue number on the single-task path, or Step 5-EPIC's **parent**
number on the multi-task path (never a child).

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
path. On the multi-task path, return the parent URL and the child URLs in dependency
order, plus the list of uploaded attachments.
