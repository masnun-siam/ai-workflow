---
description: Convert a Jira ticket to a GitHub issue
argument-hint: "<JIRA-KEY>"
---
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

3. Keep the file list for Step 5.

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

## Step 4 — Ask clarifying questions

Ask me up to 3 focused questions if anything is unclear or missing (e.g., acceptance criteria, priority override, scope labels). Wait for my answers.

## Step 5 — Create GitHub issue

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

## Step 6 — Upload attachments to GitHub issue

If attachments were downloaded in Step 2, post each as a comment on the created issue.

**For images** (png, jpg, gif, webp) — embed as base64 in markdown (works for small images <64KB):

```bash
BASE64=$(base64 -i "$TMPDIR/<filename>")
gh issue comment <ISSUE_NUMBER> --repo <OWNER/REPO> \
  --body "### 📎 Attachment: <filename>

![<filename>](data:<mime_type>;base64,$BASE64)"
```

If base64 is too large (>64KB), fall back to noting the file:

```bash
SIZE=$(stat -f%z "$TMPDIR/<filename>" 2>/dev/null || stat -c%s "$TMPDIR/<filename>")
gh issue comment <ISSUE_NUMBER> --repo <OWNER/REPO> \
  --body "### 📎 Attachment: <filename>

**<filename>** (${SIZE} bytes, <mime_type>)
Downloaded from Jira ticket $1. See original ticket for the file."
```

**For non-image files** (docs, zips, etc.) — note the attachment with metadata:

```bash
SIZE=$(stat -f%z "$TMPDIR/<filename>" 2>/dev/null || stat -c%s "$TMPDIR/<filename>")
gh issue comment <ISSUE_NUMBER> --repo <OWNER/REPO> \
  --body "### 📎 Attachment: <filename>

**<filename>** (${SIZE} bytes, <mime_type>)
Downloaded from Jira ticket $1 — see original Jira ticket to download the file directly."
```

Note: GitHub issue comments don't support arbitrary file uploads. For images, base64 embedding works for small files. For everything else, link back to the Jira ticket for download.

## Step 7 — Cleanup

```bash
rm -rf "$TMPDIR"
```

Return the issue URL and list of uploaded attachments when done.
