---
description: Normalize a Sentry link, a BRD file, an Obsidian note, or free text into a GitHub-issue-ready brief
argument-hint: "<sentry-url | file-path | vault-note | free text>"
---

> **Paths.** `<...>` placeholders below are keys from `aiw paths` (run it; `aiw` is
> on `PATH` via the plugin's `bin/`). Substitute the printed value; never guess a path.

Source: $ARGUMENTS

**HARD RULE — this skill only ever produces a brief. It never creates a GitHub issue and
never dispatches `/run-issue` or any pipeline station.**
- NEVER run `gh issue create`, `gh issue edit`, or any other mutating command.
- NEVER use Write, Edit, or NotebookEdit on any file in the repo.
- The only output is the `## Intake result` block described at the end of this file.

Do the following:

1. **Detect the source**, testing in this order, first match wins:
   - Argument matches `*sentry.io/*` or contains `/organizations/*/issues/` → **Sentry**.
   - Argument resolves to an existing file on disk (absolute path, or relative to the
     current directory) AND ends in `.md`, `.txt`, `.pdf`, or `.docx` → **BRD**. An
     existing file with any other extension is not a supported document shape — fall
     through to Note, then Text, rather than reading an arbitrary file's raw content into
     a brief that becomes a public GitHub issue body.
   - `obsidian vault=notes search query="$ARGUMENTS" format=json`, and one returned path's
     filename stem (without extension) exactly equals the argument → **Note**. A
     near-miss (partial match, multiple candidates, no exact stem) does NOT count — fall
     through to Text.
   - Otherwise → **Text**.

2. **Run the matched adapter.**

   **Sentry:**
   - Resolve the org/project slug from the URL. Use
     `mcp__plugin_sentry_sentry__find_organizations` and `find_projects` if the URL
     doesn't already carry them.
   - `mcp__plugin_sentry_sentry__get_sentry_resource` for the issue: title, culprit,
     full stack trace, first/last seen, status.
   - `mcp__plugin_sentry_sentry__search_events` for event count and affected user count
     on that issue.
   - If any of the above call fails with an authentication/authorization error: **stop**
     and tell the user to run Sentry authentication, then re-invoke `/intake`. Do NOT
     continue to the Text adapter — a Sentry URL read as plain text produces a useless
     brief.
   - Optionally, `mcp__plugin_sentry_sentry__analyze_issue_with_seer` for a root-cause
     hypothesis. If you use it, put its output under its own `## Seer hypothesis
     (unverified)` heading — never merge it into the factual sections below.
   - Build the brief (`type: bug`):
     ```
     ## Summary
     <title, one line on user-visible impact>

     ## Stack trace / culprit
     <culprit line, then the fenced stack trace>

     ## Occurrence
     - First seen: <date>
     - Last seen: <date>
     - Events: <count>
     - Users affected: <count>
     - Release: <release, if present>

     ## Seer hypothesis (unverified)
     <only if you called analyze_issue_with_seer>

     ## Notes
     Source: <the Sentry issue permalink>
     ```

   **BRD:**
   - `.md`/`.txt` → read with the Read tool.
   - `.pdf` → use the `anthropic-skills:pdf` skill to extract text.
   - `.docx` → use the `anthropic-skills:docx` skill to extract text.
   - Extract goals, scope, and acceptance criteria, preserving the document's own wording
     where it states them; do not paraphrase a stated acceptance criterion.
   - **Decomposition check** (same test `gh-issue.md` step 3.5 applies): if the document
     covers more than one independently-shippable outcome, list each candidate as one
     line (title + the one outcome it delivers), then `AskUserQuestion` — single question,
     one option per candidate — asking which one to run now. If it's a single outcome,
     skip straight to building the brief with no prompt.
   - Build the brief (`type: feature`) from the **chosen** candidate:
     ```
     ## Summary
     <the chosen outcome, in the BRD's own words where possible>

     ## Scope
     <what this candidate covers>

     ## Acceptance criteria
     <bulleted, from the BRD>

     ## Out of scope — candidate follow-ups
     <one line per unpicked candidate: title + the outcome it would deliver.
      Omit this section entirely if there was only one candidate.>

     ## Notes
     Source: <the absolute file path>
     ```

   **Note:**
   - `obsidian vault=notes read path="<the matched path>"`.
   - Build the brief (`type` inferred from the note's own headings/tags if evident,
     otherwise `task`):
     ```
     <the note's body, verbatim>

     ## Notes
     Source: <the vault note path>
     ```

   **Text:**
   - Build the brief (`type: task`) directly from the argument:
     ```
     ## Summary
     $ARGUMENTS

     ## Notes
     Source: raw text from /intake invocation
     ```

3. **Return the result** as the final message, exactly in this shape (no other text
   after it):

   ```
   ## Intake result
   type: <bug|feature|task|improvement>
   ---
   <the brief built in step 2>
   ```
