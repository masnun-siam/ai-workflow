# Content-oriented Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `/run-issue` and `/gh-issue` accept a Sentry link, a BRD file, an Obsidian
vault note, or free text — not only a GitHub issue number/URL — by normalizing any of
those into an issue brief through one new `/intake` command.

**Architecture:** `/intake` is a pure normalizer: one source in, one structured brief out
(`type`, `brief` markdown, `source_line`). It never creates a GitHub issue and never
dispatches the pipeline. `/gh-issue` gets a new step 0 that calls `/intake` when its
argument looks like a source rather than plain text, then proceeds unchanged. `/run-issue`
gets its existing Preflight step 1 extended: non-issue input goes through `/intake` →
`/gh-issue`, and the resulting issue number feeds the untouched pipeline from Preflight
step 2 onward.

**Tech Stack:** Markdown command/prompt files (this plugin has no application code for
commands — see `run-engine/` for the only Python in the repo, which this feature does not
touch). Sentry MCP (`mcp__plugin_sentry_sentry__*`), the `obsidian` CLI, `gh` CLI,
`anthropic-skills:pdf`/`anthropic-skills:docx` skills.

**Spec:** `docs/superpowers/specs/2026-09-21-intake-command-design.md`

## Global Constraints

- `/intake` never runs `gh issue create`, `gh issue edit`, or any mutating command — same
  hard rule `gh-issue.md` already states for itself, applied to a narrower surface.
- A Sentry MCP auth failure must stop with a message telling the user to authenticate —
  never silently fall through to the raw-text adapter.
- Vault note matching requires an **exact stem match**; anything less exact falls through
  to the raw-text adapter rather than guessing.
- No new human gate beyond the BRD multi-candidate disambiguation prompt. The three
  existing `/run-issue` Gates are untouched.
- No `run-engine`/Python changes — intake and issue creation both complete before
  `aiw init` ever runs.
- No `--body` flag on any `gh issue` call — always `--body-file` (existing repo rule,
  applies to any new call this plan adds).

---

### Task 1: `commands/intake.md`

**Files:**
- Create: `commands/intake.md`

**Interfaces:**
- Produces (consumed by Task 2 and Task 3): `/intake <arg>` returns, as its final
  message, a fenced block of the shape:
  ```
  ## Intake result
  type: bug|feature|task|improvement
  ---
  <brief markdown, ending with a `## Notes` section containing the line
  `Source: <permalink|absolute-path|vault-note-path>`>
  ```
  Callers read `type:` off the line after `## Intake result` and take everything after
  the `---` line as the brief body verbatim.

- [ ] **Step 1: Write `commands/intake.md`**

```markdown
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
     current directory) → **BRD**.
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
```

- [ ] **Step 2: Read the file back and self-review against the "No Placeholders" rule**

Check for: `TBD`, `TODO`, "implement later", bracketed placeholders left unresolved,
any step that describes what to do without showing the literal text/command. Fix
anything found before continuing.

- [ ] **Step 3: Dry-run verify — Text adapter**

Run `/intake this button breaks on Safari` in a real session. Expected: no tool calls
beyond the detection checks, a returned block with `type: task`, a `## Summary`
containing the argument text, and `Source: raw text from /intake invocation`.

- [ ] **Step 4: Dry-run verify — BRD adapter**

Create a throwaway file with two distinct feature outcomes described in it (in the
scratchpad directory, not the repo). Run `/intake <path>`. Expected: an `AskUserQuestion`
prompt listing both candidates, and after picking one, a brief with `type: feature`, a
populated `## Out of scope — candidate follow-ups` section naming the other candidate,
and `Source: <the absolute path>`.

- [ ] **Step 5: Commit**

```bash
git add commands/intake.md
git commit -m "feat(intake): add /intake to normalize Sentry/BRD/note/text into a brief"
```

---

### Task 2: `commands/gh-issue.md` — accept a source

**Files:**
- Modify: `commands/gh-issue.md:1-10` (frontmatter + opening lines)

**Interfaces:**
- Consumes: Task 1's `/intake` result shape (`## Intake result` block, `type:` line,
  `---`-delimited brief).
- Produces (consumed by Task 3): `/gh-issue` continues to return the created issue URL
  as its final line, unchanged from today — Task 3 needs nothing new from it beyond
  parsing the issue number out of that URL, which it already does.

- [ ] **Step 1: Update the frontmatter `argument-hint`**

In `commands/gh-issue.md`, replace:

```
argument-hint: "[bug | feature | task | improvement]"
```

with:

```
argument-hint: "[bug | feature | task | improvement] <details | sentry-url | file-path | vault-note>"
```

- [ ] **Step 2: Insert step 0 before the existing step 1**

In `commands/gh-issue.md`, the body currently opens with:

```
I have a ${1:-bug / feature request / task / improvement} to log as a GitHub issue.

Details: $@
```

Replace those two lines with:

```
I have a ${1:-bug / feature request / task / improvement} to log as a GitHub issue.

0. **Source check.** If `$@` matches one of `/intake`'s detectable source shapes — a
   `sentry.io` URL, an existing file path, or a vault note title that exactly matches one
   note — invoke `/intake $@` and wait for its `## Intake result` block. Use its `type:`
   value in place of `${1:-bug / feature request / task / improvement}` for the rest of
   this skill, and use everything after its `---` line as `Details:` below. Otherwise
   (plain text, no source shape matched), skip this step — `/intake`'s own text adapter
   would be a no-op wrapper here, so there's no reason to make the extra call.

Details: $@
```

(The literal `Details: $@` line stays as the fallback for the "skip this step" branch;
step 0's instruction to substitute the intake brief covers the other branch.)

- [ ] **Step 3: Read the whole file back and confirm every step from step 1 onward is
  untouched**

Diff the file against git to confirm only the frontmatter `argument-hint` and the new
step 0 changed — steps 1 through 7, the HARD RULE block, and the 4-EPIC section must be
byte-identical to before.

```bash
git diff commands/gh-issue.md
```

- [ ] **Step 4: Dry-run verify**

Run `/gh-issue <a sentry issue URL you have access to>`. Expected: `/intake` is invoked
first, its brief becomes the issue body content, the issue is created with a `Source:`
line in its Notes section, and `gh-issue-factchecker` still runs against it (step 4.5,
unchanged). Then run `/gh-issue bug the login page 500s intermittently` (plain text, no
source shape) and confirm step 0 is skipped — no `/intake` invocation — and behavior
matches pre-change `/gh-issue`.

- [ ] **Step 5: Commit**

```bash
git add commands/gh-issue.md
git commit -m "feat(gh-issue): accept a Sentry link, BRD file, or vault note via /intake"
```

---

### Task 3: `commands/run-issue.md` step 1, docs, and version bump

**Files:**
- Modify: `commands/run-issue.md` — frontmatter `argument-hint` + Preflight step 1
  (`run-issue.md:206-207`)
- Modify: `README.md` — Commands table + `## Layout` count
- Modify: `.claude-plugin/plugin.json` — version
- Modify: `CHANGELOG.md` — new entry

**Interfaces:**
- Consumes: Task 2's `/gh-issue` (unchanged return contract: final line is the created
  issue's URL).

- [ ] **Step 1: Update `run-issue.md` frontmatter `argument-hint`**

Find:

```
argument-hint: "<issue-number-or-url> [--lean]"
```

Replace with:

```
argument-hint: "<issue-number-or-url | sentry-url | file-path | vault-note | text> [--lean]"
```

- [ ] **Step 2: Rewrite Preflight step 1**

In `commands/run-issue.md`, under `## 0. Preflight`, the current step 1
(`run-issue.md:206-207`) reads:

```
1. Resolve `$ARGUMENTS` to an issue number (strip a URL if given) and note whether
   `--lean` was passed. Resolve `<owner>/<repo>` from the git remote.
```

Replace it with:

```
1. Strip `--lean` off `$ARGUMENTS` first (note whether it was passed) so every source
   below sees only the issue reference. Resolve `<owner>/<repo>` from the git remote.

   - Argument is a bare number, or a `github.com/.../issues/<n>` URL → resolve to `<n>`,
     unchanged from before.
   - Anything else (a Sentry link, a file path, a vault note title, or free text) →
     invoke `/intake $ARGUMENTS`, then invoke `/gh-issue` passing its `type:` and brief
     through exactly as `/gh-issue`'s own step 0 does. Parse the created issue number `<n>`
     from `/gh-issue`'s returned URL. Continue to Preflight step 2 with that `<n>` as
     though it had been passed to `/run-issue` directly.
```

- [ ] **Step 3: Read the whole file back and confirm nothing past step 1 of Preflight
  changed**

```bash
git diff commands/run-issue.md
```

Expected: only the frontmatter `argument-hint` line and Preflight step 1 differ; steps 2
onward (dirty-tree check, `gh issue view`, epic check, resume check) are byte-identical.

- [ ] **Step 4: Update `README.md`**

In the Commands table (`README.md:204-210`), add a row directly under the `run-issue`
row:

```
| `/ai-workflow:intake <source>` | normalize a Sentry link, BRD file, or vault note into an issue brief — used internally by `/gh-issue` and `/run-issue` |
```

In `## Layout` (`README.md:252`), change:

```
commands/     run-issue (the orchestrator) + 4 intake commands
```

to:

```
commands/     run-issue (the orchestrator) + 5 intake commands
```

- [ ] **Step 5: Bump `.claude-plugin/plugin.json` version**

Current `"version": "1.2.1"`. This is a new feature (accepts new input types), not a
patch — bump to `"1.3.0"`.

- [ ] **Step 6: Add a `CHANGELOG.md` entry**

At the top of `CHANGELOG.md`, above the existing `## 1.2.1` entry, add:

```markdown
## 1.3.0 — 2026-09-21

### Added

- **Content-oriented intake.** `/run-issue` and `/gh-issue` now accept a Sentry issue
  link, a BRD file path, an Obsidian vault note, or free text — not only a GitHub issue
  number/URL. A new `/intake` command normalizes any of those into an issue brief
  (auto-detected, no flags); `/gh-issue` files it as a real issue exactly as it would a
  hand-written description, and `/run-issue` runs `/intake` then `/gh-issue` automatically
  when its argument isn't already an issue reference. The GitHub issue stays the single
  source of truth — nothing downstream of Preflight step 1 changed. A BRD describing more
  than one independently-shippable outcome prompts once to pick which one to run now; every
  other source never prompts.
```

- [ ] **Step 7: Dry-run verify end to end**

Run `/run-issue <a sentry issue URL you have access to>` through Gate 1 only (stop
before approving the plan). Confirm: `/intake` then `/gh-issue` ran, a real issue was
created with a `Source:` line, `00-readiness.json` exists in the run dir and scored
against the created issue, and Gate 1 shows a plan. Abort there. Then run `/run-issue
<that same issue number> --lean` — expected: `status: "done"` is not set yet since you
aborted, so this resumes; confirm the resume path still works and `--lean` is honored.
Finally run `/run-issue <an existing, already-numbered issue>` and confirm Preflight
goes straight to `gh issue view` with no `/intake` call — the unchanged path.

- [ ] **Step 8: Commit**

```bash
git add commands/run-issue.md README.md .claude-plugin/plugin.json CHANGELOG.md
git commit -m "feat(run-issue): route non-issue input through /intake + /gh-issue, bump to 1.3.0"
```
