---
description: Create a GitHub issue with codebase context
argument-hint: "[bug | feature | task | improvement] <details | sentry-url | file-path | vault-note> [--review [<lens,lens>] [--herdr]]"
---

> **Paths.** `<...>` placeholders below are keys from `aiw paths` (run it; `aiw` is
> on `PATH` via the plugin's `bin/`). Substitute the printed value; never guess a path.
I have a ${1:-bug / feature request / task / improvement} to log as a GitHub issue.

0. **Source check.** Before anything else, remove `--review`, the token after it when that token
   doesn't start with `--` (the picked lenses), and `--herdr` from `$@`, and remember them for
   **Peer review** below. Every later `$@` in this file, including the `/intake` call, means the
   stripped value, so `/intake` never reviews the brief a second time.
   **A vault `Bugs.md` or `Tasks.md` note** (a path ending in `/Bugs.md` or `/Tasks.md`, as
   `/dump` names it in `→ next: /gh-issue <note-path>`) is handled here and never sent to `/intake`.
   Read it with `obsidian vault=notes read path="<path>"`. `Bugs.md` holds every bug of the feature,
   one `## <date>: <title>` block each; `Tasks.md` holds every task, one `- [ ] <date>: <text>` line
   each (unchecked lines only). Work on one: with one, take it; with more, ask which one (see
   **Asking the user**), newest first (the newest is the one right above `## Related`); in Flow auto
   mode take the newest without asking. Use only the chosen block as `Details:` below, and its type
   (`bug` from `Bugs.md`, `task` from `Tasks.md`) in place of
   `${1:-bug / feature request / task / improvement}`. Record
   `Source: <path> — <block heading>` in the created issue's **Notes**. Then skip the `/intake`
   check below.
   Otherwise, if `$@` matches one of `/intake`'s detectable source shapes — a
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

### Asking the user

A headless run (started from the workflow UI) has no terminal to answer in, so
`AskUserQuestion` is not available there. You are headless when your system prompt contains
`Headless run: ask via aiw ask`. At every question below, the same header, question and options
are used either way; only the transport differs.

- **Headless:** call the command below. Use the quoted heredoc: issue text may embed arbitrary
  text, so never put it inside single quotes on the command line. Starts with `aiw `.

  ```
  # one call per round
  aiw ask <<'EOF'
  {"questions":[{"header":"...","question":"...","multiSelect":false,"options":[{"label":"...","description":"..."}]}]}
  EOF
  ```

  Every question in steps 3 to 6 below follows this; one `aiw ask` per grilling round, one question per numbered question (header `Q<n>`, `multiSelect` false), options are the choices the question names, and a question naming no choices carries its recommended answer as the single option. List the recommended option first with `(Recommended)` on its label. Free text is
  always allowed. Then end your turn immediately and do nothing else; the answer arrives as
  your next message, `Answer to q-...: {"0":{"labels":["..."]}}` or
  `{"0":{"other":"free text"}}`. Strip any ` (Recommended)` suffix from the label and take
  the same branch the interactive answer would. Free text that names no option is feedback for
  that question, never an approval.
- **Otherwise:** not headless, so skip `aiw ask` and call AskUserQuestion exactly as written at the question.

### Flow auto mode

When the system prompt contains `Flow auto mode`, this run is the Issues step of the aiw ui
guided Flow. Its input is a `Bugs.md` or `Tasks.md` note (step 0); there is no PRD. Ask only
grilling questions; settle every other choice as follows and list what you decided in the final
report:

- **Step 3 (grilling):** take requirements, acceptance criteria, priority, users and corner cases
  from the chosen block. Ask its **Open questions** as grilling questions. One that cannot be
  asked (it needs someone not in the session) is written into the issue's Assumptions, never
  guessed silently.
- **Task list (3.5):** 2 or more tasks stop as 3.5 says; Flow auto mode never files a partial list.
- **Assignee (step 5):** only the authenticated user (`gh api user --jq .login`).
- **Project (step 6):** the project(s) linked to the repo
  (`gh repo view <owner>/<repo> --json projectsV2 --jq '.projectsV2.Nodes'`); if several,
  the most recently updated one. If none is linked, use the owner's project when
  `gh project list` shows exactly one; otherwise add to no project and say so.
- **Project fields:** a field named `Status` (or the single-select field that plays that role)
  gets its first option. Every other single-select field gets the option that best fits the
  issue's content and the PRD (for example Priority from the PRD's priority). Never invent option
  names. List every value set, per issue, in the report.
- **Step 7:** the `/dump` it invokes runs in Flow auto mode too, so its confirmation is skipped.
- **Hand-off line:** print the `→ next:` line as text only. Never invoke `/create-prd`, the
  `herdr-dispatch` skill or the `herdr` CLI, or open tabs; the UI's next steps do that.


**HARD RULE — while executing steps 0–7 below, this skill only ever creates a GitHub issue.
It never touches code.**
- NEVER use Write, Edit, or NotebookEdit on any file in the repo.
- NEVER run a mutating shell command (`git commit`, `git checkout -b`, package installs, formatters, codemods, etc.).
- The ONLY writes permitted are the **Peer review** draft under `<data_dir>` (outside the repo), the temp body file at `/tmp/gh-issue-body.md`, the `gh issue create` / `gh issue edit` / `gh project` calls below, `aiw ask` when headless (records the question in the UI session, outside the repo), and the notes-vault dump in step 7 (that's a different vault, not the repo, and goes through the `dump` skill's own confirmation).
- This holds even for a one-character fix. "It's trivial" is not an exception — the whole point of filing an issue is that a human decides whether and how to make the change.
- If a fix is obvious from your investigation, do NOT apply it. Record it under a **Proposed Fix** section in the issue body instead (file path, symbol, and the change in prose or a fenced diff).
- **Scope.** These constraints bind steps 0–7 of this skill only. When `/run-issue` invoked
  this skill, they lapse the moment the issue URL is returned — the caller's later phases write
  code by design, and this rule must not be carried into them.

Do the following:

1. Use GitNexus MCP (`gitnexus_query`, `gitnexus_context`) to find the relevant code — execution flows, affected symbols, and files related to this description.
2. Check git status and recent commits for any in-progress work that touches the same area.
2.5. Dispatch the `run-researcher` agent (haiku, read-only) with the description above and the `owner/repo` slug, to collect context *outside* the codebase: prior related issues/PRs, project wiki, relevant public docs (library/API behavior the description implies). Carry its brief into steps 3 and 4 — do not print it verbatim, fold the relevant parts into the grilling and the issue body. Best-effort: if it errors or returns nothing useful, note that in one line and continue without it.
3. Use the grill-me skill to interview me on anything unclear (acceptance criteria, priority, affected users, edge cases), asking via the AskUserQuestion tool (if headless, `aiw ask` per round instead, then end your turn). Wait for my answers.
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

   Present the list in exactly one `AskUserQuestion` call (if headless, one `aiw ask`, then end your turn) with two choices, verbatim:
   **"Create as shown"** and **"Let me edit the list"**.
   Style this like Gate 1's revise loop in `commands/run-issue.md`:

   - **"Let me edit the list"**: take the free-text feedback, revise the list, re-apply
     the rubric (a requested merge that would break a limit is declined, with the reason
     shown), and present the same question again. Loop until **"Create as shown"**
     is picked. No round limit.
   - **"Create as shown"**: route on the approved list's task count. 1 task goes to step 4.
     2 or more tasks: this is PRD-sized work, so this command creates nothing. Print the
     approved list (it is the starting point for the PRD), say "This splits into <k> tasks;
     write a PRD first so they get an epic, waves and refined sub-issues", and end with
     `→ next: /create-prd <input>` (printed under `/run-issue` too, which branches on it; the original argument: a path or URL as given; for free
     text, the vault feature folder when one is already known, such as from step 2.5's
     research brief, otherwise the text in double quotes). Skip steps 4–7 and the return below.
4. Then create a GitHub issue on the current repo:
   - With `--review`, run **Peer review** (below) on the body before this create, and file the reviewed body.
   - Write the full body to `/tmp/gh-issue-body.md` using the write tool
   - Every issue this command creates carries the `refined` label (unconditional). Ensure it
     exists once per run, before the first create (idempotent, cheap):
     ```bash
     gh label create refined --color 1D76DB --description "properly specified: passes the issue template" 2>/dev/null || true
     ```
   - Run `gh issue create --title "..." --label "refined,..." --body-file /tmp/gh-issue-body.md`; ask step 5's assignee question and step 6's project and field questions first, and add their `--assignee` / `--project` flags to this create
   - **NEVER use `--body` flag** — shell escaping breaks on backticks, pipes, quotes, newlines. Always `--body-file`.
   - Delete `/tmp/gh-issue-body.md` after the issue is created
   - Title: clear, specific, ≤72 chars
   - Body sections: **What** (the change: the business requirements, plus repro steps for a bug or requirements for a feature), **Why** (the problem and *why it matters* — not a restatement of the fix), **Out of Scope**, **Context / Affected Code** (file paths and symbols from step 1), **Acceptance Criteria** (include every corner case validated in step 3 as its own explicit criterion), **How** (ordered numbered steps; exact path:line/symbol references reusing the GitNexus lookup from step 1; an existing pattern to copy, or "no existing pattern — net-new"; the exact test/verify command(s); a one-line done-check; a `Test root: <repo-relative dir>` line naming where this issue's tests live, plus `Base branch: <branch>` when the PR should not target the default branch — `/run-issue` reads both to skip its researcher and planner), **Non-functional Constraints**, **Assumptions**, **Dependencies / Blockers**, **Proposed Fix** (only if a concrete fix is obvious — describe it, do NOT apply it), **Notes**
   - **These sections are `/run-issue`'s Definition of Ready.** `run-researcher` scores every issue against `<dor>` and surfaces each gap at Gate 1 as a "thin issue" warning (advisory, it does not stop the run); a `refined` issue that passes `aiw refined` skips the researcher entirely, so these sections are the only readiness check it gets. Read that file; it is six items and this section list is one-to-one with it.
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

4.5. Dispatch the `gh-issue-factchecker` agent (fresh context, no memory of the steps above) with just the created issue's number/URL and `owner/repo`. It re-reads the created issue cold and checks every concrete claim (file paths, symbols, described behavior, the proposed fix) against the real repo. Tell it explicitly: a `Source:` line in the Notes section pointing outside the repo (a Sentry permalink, an absolute file path, or a vault note path) is expected traceability from `/intake`, not a claim about this repo, and must not be flagged as an unverifiable claim.
   - `PASS` → continue with step 5, no mention needed.
   - `ISSUES FOUND` → fix the flagged text yourself, write the corrected body to `/tmp/gh-issue-body.md`, run `gh issue edit <n> --body-file /tmp/gh-issue-body.md`, delete the temp file, and briefly tell me what was wrong and corrected. Do not silently ignore a flagged discrepancy.
5. Assign the issue:
   - Ask this once, before step 4's create.
   - Get the default assignee: `gh api user --jq .login`.
   - Confirm via AskUserQuestion (`multiSelect: true`), with that login (as `@me`) recommended first, alongside other repo collaborators from `gh api repos/{owner}/{repo}/assignees --jq '.[].login'` (if headless, `aiw ask`, then end your turn).
   - Pass each chosen login as its own `--assignee <login>` flag on the `gh issue create` (combine with the create call in step 4 rather than a separate call).
6. Add to a GitHub Project and fill its fields, discovered at runtime — never assume a project or field schema:
   - Ask the project and field questions once, before step 4's create.
   - `gh project list --owner <repo-owner> --format json`
     - Zero projects → skip this step entirely, go straight to returning the URL.
     - One project → use it.
     - Multiple → ask via AskUserQuestion (`multiSelect: true`) which ones (if headless, `aiw ask`, then end your turn).
   - Add the issue to each chosen project at creation time, one `--project "<title>"` flag per project on the create (same call as step 4/5).
   - For each chosen project, read its fields: `gh project field-list <number> --owner <owner> --format json`.
   - For each `ProjectV2SingleSelectField` on each project, ask the user to pick from that field's real `options` (never invent option names) — batch into as few AskUserQuestion calls as possible (max 4 questions per call). Skip any field the user declines to set. If headless, use `aiw ask` (one round, up to 4 questions), then end your turn.
   - Set each chosen field on the issue — **one field per `item-edit` call** (the CLI only supports single-field updates on non-draft issues):
     `gh project item-edit <number> --owner <owner> --url <issue-url> --field "<name>" --value "<option>"`
   - If any `gh project` call fails, don't abort — the issue already exists and is assigned; keep going with the remaining fields. Report the issue URL and state plainly which fields couldn't be set and why (a missing `project` token scope is the likely cause; fix with `gh auth refresh -s project`).
   - Verify project fields landed on the issue with `gh issue view <n> --repo <owner>/<repo> --json projectItems` — cheap, and confirms per-project field values (e.g. Status) directly on the issue. Do NOT verify by paginating `gh project item-list` (projects can hold hundreds/thousands of items — pulling the full list to find one issue wastes time and burns context).
7. Dump the gathered context into the notes vault so it's there next time. Invoke the
   `ai-workflow:dump` skill, passing it: the issue title and URL, the final issue body, and the
   decisions from the step-3 grilling that did NOT make it into the body verbatim
   (rejected alternatives, corner cases ruled out and why, priority/scope calls). If
   step 2.5's research brief named a `feature folder`, state it as the proposed target so
   `/dump` doesn't re-derive it.

   `/dump` classifies, proposes a target, and confirms with you before writing — let it.
   Do not pre-empt or skip its confirmation (outside Flow auto mode, see above).

   Best-effort: if the vault is unreachable or `/dump` is cancelled, say so in one line.
   The issue already exists and is the deliverable; the dump is not worth failing over.

Return the issue URL. On a standalone run, end with `→ next: herdr-dispatch <n>`; it is the last line of
your output and the Guided Flow parses it. If `/run-issue` invoked this skill, print no
`→ next: herdr-dispatch` line: hand control back to its Preflight
step 3 with that issue number and continue the run; the HARD RULE above no longer applies.

## Peer review (only with `--review`)

One review covers the issue, before the first `gh issue create`, once step 4 has written its body.
Nothing reaches GitHub unreviewed.

1. `aiw peer-review new gh-issue --slug <owner>-<repo>-<slug>` (`<slug>`: kebab-case from the
   issue title) prints `<review_dir>`.
2. Write `<review_dir>/draft.md` with the Write tool: one `## Issue 1: <title>` section holding
   the issue's full body.
3. Invoke the `ai-workflow:peer-review` skill with
   `--kind gh-issue --dir <review_dir> --lenses <picked>` (plus `--herdr`). It revises
   `draft.md` in place and asks the user any decisions.
4. On its `stopped` finish, create nothing and report. Otherwise file the reviewed body from
   `draft.md`. Accepted gaps go into the issue's Notes as known gaps.

The post-create factchecker (step 4.5) still runs: the panel checks the draft, the factchecker
checks the filed issue's claims against the repo.
