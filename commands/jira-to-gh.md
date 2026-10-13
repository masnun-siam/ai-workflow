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

Present the list in exactly one `AskUserQuestion` call (if headless, one `aiw ask`, then end your turn) with two choices, verbatim:
**"Create as shown"** and **"Let me edit the list"**.
Style this like Gate 1's revise loop in `commands/run-issue.md`:

- **"Let me edit the list"**: take the free-text feedback, revise the list, re-apply
  the rubric (a requested merge that would break a limit is declined, with the reason
  shown), and present the same question again. Loop until **"Create as shown"**
  is picked. No round limit.
- **"Create as shown"**: route on the approved list's task count. 1 task goes to Step 5.
  2 or more tasks: this is PRD-sized work, so this command creates nothing. Print the
  approved list (it is the starting point for the PRD), say "This splits into <k> tasks;
  write a PRD first so they get an epic, waves and refined sub-issues", and end with
  `→ next: /create-prd <jira-key-or-url>` (the Jira key or URL given as `$1`). Skip Steps 5
  and 6, but run Step 7's cleanup before that last line.

## Step 5 — Create GitHub issue (single-task path)

This step runs when exactly 1 task was approved in Step 4.5.

Write one complete, DoR-passing body, with Jira context from Step 3 inlined, to
`/tmp/gh-issue-body.md` using the write tool:

- Body sections: **What** (the change: the business requirements, plus repro steps for a bug or requirements for a feature), **Why** (the problem and *why it matters* — not a restatement of the fix), **Out of Scope**, **Context / Affected Code** (file paths and symbols from Step 4.5's GitNexus lookup), **Acceptance Criteria** (include every corner case surfaced in Step 4's clarifying Q&A as its own explicit criterion), **How** (ordered numbered steps; exact path:line/symbol references reusing the GitNexus lookup from Step 4.5; an existing pattern to copy, or "no existing pattern — net-new"; the exact test/verify command(s); a one-line done-check; a `Test root: <repo-relative dir>` line naming where this issue's tests live, plus `Base branch: <branch>` when the PR should not target the default branch — `/run-issue` reads both to skip its researcher and planner), **Non-functional Constraints**, **Assumptions**, **Dependencies / Blockers**, **Proposed Fix** (only if a concrete fix is obvious — describe it, do NOT apply it), **Notes** (include the Jira key/URL here as traceability)

The issue carries
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

## Step 6 — Upload attachments to GitHub issue

If attachments were downloaded in Step 2, post each as a comment on `<TARGET_ISSUE>`, the
issue created in Step 5.

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

Return the issue URL and the list of uploaded attachments.
