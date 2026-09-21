# Content-oriented intake for `/run-issue` — design

## Context

`/run-issue` can only start from a GitHub issue. `commands/run-issue.md:206` is literally
"Resolve `$ARGUMENTS` to an issue number (strip a URL if given)". In practice work arrives
as a Sentry link, a BRD, a vault note, or a sentence in chat — and each of those means
hand-writing an issue first before the pipeline is allowed to touch it.

Goal: accept those sources directly, while the GitHub issue stays the single source of
truth (so PR linking, `00-readiness.json`, epic mode, and the run-dir naming
`<owner>-<repo>-issue-<n>` all keep working untouched). Nothing downstream of
`run-issue.md` step "0. Preflight" #1 changes.

## Decisions

- Non-issue input is **always materialized into a real GitHub issue** before the pipeline
  runs.
- Sources on day one: Sentry issue link, BRD file path, Obsidian vault note, raw text.
- **Auto-detected** from the argument — no flags.
- Normalization lives in a **new `/intake` command**; `/gh-issue` and `/run-issue` both
  call it.
- **No new human gate.** Exception: when a source decomposes into >1 candidate issue
  (realistically only a BRD), `/intake` asks which slice to run. That is input
  disambiguation, not a Gate — the three existing Gates (`run-issue.md` plan approval,
  escalated review finding, ready-to-merge handback) are unchanged.

## Design

### 1. New `commands/intake.md`

`argument-hint: "<sentry-url | file-path | vault-note | free text>"`

One job: **one source → one issue brief.** It does not create issues (no `gh issue
create`) and does not dispatch the pipeline.

Detection, first match wins, run in this order:

| Test | Adapter |
|---|---|
| arg matches `*sentry.io/*` or contains `/organizations/*/issues/` | Sentry |
| arg resolves to an existing file on disk (absolute or relative to cwd) | BRD |
| arg exactly matches a note title in the vault (`obsidian vault=notes search
  query="<arg>" format=json`, then require an exact stem match against the returned
  paths) | Note |
| none of the above | raw text (passthrough) |

Adapters:

- **Sentry** — `mcp__plugin_sentry_sentry__find_organizations` /
  `find_projects` to resolve the slug from the URL, then
  `mcp__plugin_sentry_sentry__get_sentry_resource` for the issue detail (title, culprit,
  stack trace, first/last seen) and `search_events` for event/user counts. Optionally
  `analyze_issue_with_seer`, its output kept under its own `## Seer hypothesis (unverified)`
  heading — never merged into the factual sections. Emits a **bug** brief.
  If any Sentry MCP call returns an auth error, stop and tell the user to authenticate —
  do not fall through to the raw-text adapter; a Sentry URL treated as text produces a
  useless issue body.
- **BRD** — `Read` for `.md`/`.txt`; the `anthropic-skills:pdf` skill for `.pdf`, the
  `anthropic-skills:docx` skill for `.docx`. Extract goals, scope, acceptance criteria
  verbatim where stated. Emits **feature**.
- **Note** — `obsidian vault=notes read path="<matched path>"`, same CLI every other
  vault-touching agent in this plugin uses (`dump`, `run-researcher`,
  `worklog-runner`). A near-miss (no exact stem match) falls through to the raw-text
  adapter rather than guessing which note was meant.
- **Text** — passthrough, arg becomes the brief body directly.

Decomposition: an adapter may report more than one candidate issue (in practice only the
BRD adapter, on a brief describing multiple independently-shippable outcomes — the same
test `gh-issue.md` step 3.5 already applies). When it does, `AskUserQuestion` (single
question, one option per candidate, one-line title + outcome each) picks which one to
run now. The unpicked candidates are written into the winning brief under a
`## Out of scope — candidate follow-ups` heading, so they're visible at Gate 1 and not
silently dropped.

Output — a single structured result, not printed to the user, returned to the caller
command:

- `type`: `bug | feature | task | improvement`
- `brief`: full markdown body (the BRD/Sentry/note content, or the raw text verbatim)
- `source_line`: exactly one line, `Source: <sentry-permalink | absolute-file-path |
  vault-note-path>` — the only traceability back to the origin, and it MUST appear in
  the brief's `## Notes` section so `gh-issue.md` step 4 doesn't have to be told about it
  separately.

### 2. `commands/gh-issue.md` — accept a source

Current arg handling (`gh-issue.md:1-10`):

```
description: Create a GitHub issue with codebase context
argument-hint: "[bug | feature | task | improvement]"
---
I have a ${1:-bug / feature request / task / improvement} to log as a GitHub issue.

Details: $@
```

New step 0, inserted before the existing step 1 (`gh-issue.md:19-21`): if `$@` matches
one of the three detectable source shapes (Sentry URL, existing file path, exact vault
note title), invoke `/intake $@` and use its `brief` as the `Details:` text and its
`type` in place of `${1:-...}` for the rest of the skill. If `$@` matches none of them
(plain text), skip `/intake` and proceed exactly as today — `/intake`'s raw-text adapter
would be a no-op wrapper in that case, so this avoids a redundant hop.

Everything after that step is reused unchanged: the `run-researcher` dispatch at step
2.5, the grill-me interview at step 3, the epic check at step 3.5, issue creation at step
4, the `gh-issue-factchecker` dispatch at step 4.5, assignment, project fields, and the
vault dump at step 7.

`argument-hint` becomes `"[bug | feature | task | improvement] <details | sentry-url |
file-path | vault-note>"`.

### 3. `commands/run-issue.md` — step 1 only

At `run-issue.md:206-207` ("0. Preflight", step 1):

- `$ARGUMENTS` (after stripping `--lean`) is a bare number or a
  `github.com/.../issues/<n>` URL → unchanged path, resolve to `<n>` as today.
- Otherwise → invoke `/intake` with the same argument, then invoke `/gh-issue` passing
  the intake result through (brief as `Details:`, `type` as the issue type), capture the
  created issue's number from `/gh-issue`'s return, and continue Preflight step 2 as
  though that number had been passed originally.
- `--lean` is stripped from `$ARGUMENTS` before source detection runs (as it already is
  before number/URL detection), so it composes with every source.

`argument-hint` becomes `"<issue-number-or-url | sentry-url | file-path | vault-note |
text> [--lean]"`.

No `run-engine` change: intake and `/gh-issue` both run before `aiw init`, so this
produces nothing the router, `run.json`, or any station envelope needs to know about —
by the time Preflight step 3 (`gh issue view`) runs, there is always a real issue number.

## Files

- **new** `commands/intake.md`
- `commands/run-issue.md` — step 1 dispatch rule (`run-issue.md:206-207`) + frontmatter
  `argument-hint`
- `commands/gh-issue.md` — new step 0 + frontmatter `argument-hint`
- `README.md` — Commands table row for `/intake`; `## Layout` count
  ("4 intake commands" → "5 intake commands")
- `.claude-plugin/plugin.json` — version bump
- `CHANGELOG.md` — new entry

## Reuse (do not rebuild)

- `commands/gh-issue.md` step 2.5 `run-researcher` dispatch, step 3.5 epic split, step
  4.5 `gh-issue-factchecker` dispatch, step 7 vault dump
- `obsidian` CLI, exact invocation pattern from `agents/run-researcher.md:49` and
  `skills/dump/SKILL.md`
- Sentry MCP tools (`mcp__plugin_sentry_sentry__*`)
- `anthropic-skills:pdf`, `anthropic-skills:docx`
- `run-engine/route.py` — untouched, no engine test changes needed

## Verification

1. `/intake` alone against: a real Sentry issue URL, a sample BRD markdown file, an
   existing vault note title, and a plain sentence. Confirm `type`, a correct
   `source_line`, and — for a multi-outcome BRD — the candidate-slice prompt plus the
   `## Out of scope` section in the losing candidates.
2. `/intake` against a Sentry URL with the Sentry MCP unauthenticated → confirm it stops
   with an auth message rather than falling through to raw text.
3. `/gh-issue <sentry-url>` → confirm one issue is created carrying the `Source:` line
   and that `gh-issue-factchecker` still runs against it.
4. `/run-issue <sentry-url>` end to end to Gate 1, inspect the created issue and
   `00-readiness.json`, then abort. Repeat with `<sentry-url> --lean` to confirm flag
   composition.
5. `/run-issue 41` (a real existing issue number) → confirm the path is unchanged: no
   `/intake` invocation happens, Preflight proceeds straight to `gh issue view`.

## Risks

- Bare-word ambiguity between a vault note title and raw text — mitigated by requiring
  an exact stem match; anything less exact falls through to text.
- A mis-scoped BRD slice burns a researcher + planner cycle before a human sees it; Gate
  1 is the backstop, matching the existing risk `gh-issue.md`'s own epic-split already
  carries.
- `/intake` becoming a dumping ground for unrelated logic over time — its contract stays
  one source in, one brief out; anything that creates an issue or runs a pipeline
  belongs in `/gh-issue` or `/run-issue`.
