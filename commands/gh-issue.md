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

**HARD RULE — while executing steps 0–7 below, including everything under `4-EPIC`
(note: `4-EPIC` has its own internal 1–7 numbering; that's a sub-branch of top-level
step 4, not a separate range, and it is still fully bound by this rule), this skill only
ever creates a GitHub issue. It never touches code.**
- NEVER use Write, Edit, or NotebookEdit on any file in the repo.
- NEVER run a mutating shell command (`git commit`, `git checkout -b`, package installs, formatters, codemods, etc.).
- The ONLY writes permitted are the temp body file at `/tmp/gh-issue-body.md`, the `gh issue create` / `gh issue edit` / `gh project` calls below, and the notes-vault dump in step 7 (that's a different vault, not the repo, and goes through the `dump` skill's own confirmation).
- This holds even for a one-character fix. "It's trivial" is not an exception — the whole point of filing an issue is that a human decides whether and how to make the change.
- If a fix is obvious from your investigation, do NOT apply it. Record it under a **Proposed Fix** section in the issue body instead (file path, symbol, and the change in prose or a fenced diff).
- **Scope.** These constraints bind steps 0–7 of this skill only, including everything
  under `4-EPIC`. When `/run-issue` invoked this skill, they lapse the moment the issue
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

   More than ~8 tasks is a decomposition problem, not a bigger epic: create nothing and
   don't ask yet — say so, then rebuild the list coarser once before presenting it.

   Present the list in exactly one `AskUserQuestion` call with three choices, verbatim:
   **"Create as shown"**, **"Let me edit the list"**, **"File as one issue instead"**.
   Style this like Gate 1's revise loop in `commands/run-issue.md`:

   - **"Let me edit the list"**: take the free-text feedback, revise the list, re-apply
     the more-than-8 guard, and present the same question again. Loop until one of the
     other two choices is picked. No round limit.
   - **"Create as shown"**: route on the approved list's task count, not on the choice
     itself — 1 task goes to step 4 (single issue, unchanged); 2 or more tasks go to
     4-EPIC, in the list's dependency order.
   - **"File as one issue instead"**: go to step 4 with the full grilled requirements,
     bypassing 4-EPIC entirely, regardless of how many tasks were on the list.
4. Then create a GitHub issue on the current repo:
   - Write the full body to `/tmp/gh-issue-body.md` using the write tool
   - Run `gh issue create --title "..." --label "..." --body-file /tmp/gh-issue-body.md`
   - **NEVER use `--body` flag** — shell escaping breaks on backticks, pipes, quotes, newlines. Always `--body-file`.
   - Delete `/tmp/gh-issue-body.md` after the issue is created
   - Title: clear, specific, ≤72 chars
   - Body sections: **Summary** (the problem and *why it matters* — not a restatement of the fix), **Specific Business Requirements**, **Out of Scope**, **Context / Affected Code** (file paths and symbols from step 1), **Steps to Reproduce / Requirements**, **Acceptance Criteria** (include every corner case validated in step 3 as its own explicit criterion), **Implementation Guide** (ordered numbered steps; exact path:line/symbol references reusing the GitNexus lookup from step 1; an existing pattern to copy, or "no existing pattern — net-new"; the exact test/verify command(s); a one-line done-check), **Non-functional Constraints**, **Assumptions**, **Dependencies / Blockers**, **Proposed Fix** (only if a concrete fix is obvious — describe it, do NOT apply it), **Notes**
   - **These sections exist to clear `/run-issue`'s Gate 0.** `run-researcher` scores every issue against `<dor>` and *blocks the run* on a gap, so an issue filed without them gets bounced back to you with a `needs-info` comment. Read that file; it is six items and this section list is one-to-one with it.
     - **Out of Scope** — always at least one real entry. An issue with no stated edge is an issue whose PR grows one.
     - **Non-functional Constraints** — performance, security, authorization, data migration, backward compatibility. Write `none` deliberately where it's true; silence scores as unconsidered, `none` scores as answered.
     - **Assumptions** — anything you filled in that the issue's author didn't say, stated so they can correct it. This is the section that keeps a normalization from becoming invented scope.
     - **Dependencies / Blockers** — its own section, not a line in Notes. `none` beats silence here too.
     - Never delete one of these five to avoid writing `none`, and never ship a body containing `[bracketed placeholders]` — that is a failed run, not a draft.
   - **Implementation Guide is not a DoR item** — it's the plan, not a readiness gate.
     Required on every issue except an epic parent. Every step names a real path:line
     or symbol — no vague area names like "the auth code." A `[bracketed placeholder]`
     in it counts as a failed run under the same rule as the four sections above.
     When a **Proposed Fix** section is also present, it stays the literal patch;
     Implementation Guide is the ordered plan to get there.
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

### 4-EPIC. Create the parent and its children

1. Create the **parent** with the BRD as its body, labelled `epic`. It is a container:
   it needs no acceptance criteria of its own, and it is **never** labelled `lean` — a
   container spans however many children it has, which is never "one to two files or
   symbols touched."
2. For each child, write a **complete, independently DoR-satisfying** issue body — the
   same section list as step 4, with the parent's context **inlined, never referenced**.
   `run-researcher` scores each child on its own and blocks the run on a gap, so a child
   whose Context section says "see parent" dies before its worktree is created.

   Each child is one **vertical slice** — one thin end-to-end outcome, never a layer.
   Horizontal slices ("all the models") maximize file overlap, which serializes the DAG,
   and none of them has acceptance criteria that can be verified on their own. Each
   child's Implementation Guide covers only that child's own slice — never a step that
   touches a sibling's files or refers to a sibling's steps.

   Where a child depends on a sibling, add a line on its own:

   ```
   Depends on: #<n>, #<n>
   ```

   Edges may only point at siblings in this epic.
2.5. Create children one at a time, in the approved list's order. Before writing child
   k's body, replace each `task <j>` placeholder from step 3.5's list with the real
   `#<n>` issue number already returned for child j (child j must have been created
   first — this is why order matters).

   Include `epic-<parent>` in each child's `--label` list on its `gh issue create` call,
   alongside its normal labels — apply it at creation time, not afterward. Deferring the
   label to a later step means a child created mid-loop, before a later sibling's create
   call fails, would never carry it if the run stops before that later step runs; the
   loop can end at any child, and every child already created must be immediately
   findable via `gh issue list --label epic-<parent>` regardless of where the loop
   stopped. When `epic-<parent>` is about to be applied for the first time this run,
   ensure it exists first (idempotent, cheap):
   ```bash
   gh label create epic-<parent> --color 5319E7 --description "child of epic #<parent>" 2>/dev/null || true
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
   - **"Stop here"**: end the run, report the partial state (created vs. missing), do
     NOT call `aiw epic split` (it only runs once every planned child exists — see step
     4), and return no issue URL/number to the caller — `/run-issue`'s own preflight
     then correctly stops instead of treating an unlinked parent as a complete epic.

   Never auto-close or delete issues already created — a partial epic is a recoverable
   state, not a failure state.
3. Judge each child against step 4's `lean` heuristic **independently, against its own
   body** — a child's own outcome, file count, dependency, API-surface and risk-area
   answers, not the epic's aggregate. (`epic-<parent>` was already applied at creation
   time in step 2.5 — see above.) The same idempotent ensure-create from step 4 runs
   once, before the first child that earns the `lean` label:
   ```bash
   gh label create lean --color 0E8A16 --description "small, well-specified: run lean roster" 2>/dev/null || true
   ```
4. Link and validate. This step only runs once every planned child exists — step 2.5's
   partial-failure gating is what guarantees that:

   ```bash
   aiw epic split "<runs_dir>/<owner>-<repo>-epic-<parent>" \
     --parent <parent> --slug <owner>/<repo> --children <n>,<n>,<n>
   ```

   Exit 1 means the edges do not form a DAG — a cycle, a self-edge, or an edge pointing
   outside the epic. Fix the offending child's `Depends on:` line with `gh issue edit`
   and re-run. Do not proceed with an invalid DAG: the ordering is what keeps a stacked
   child from branching off a base that does not exist yet. This call also writes the
   parent's `## Tasks` checklist in dependency order, so there is no separate `gh issue
   edit` needed for it.
5. Step 4.5 (the `gh-issue-factchecker` dispatch) runs **once per child** — each child
   body makes its own concrete claims about files and symbols, and that is exactly what
   the factchecker verifies; a check against the parent would miss them. Step 5
   (assignee confirmation) is asked **once**, and the chosen assignees are applied to the
   parent and every child — asking once per child is the interruption-multiplying pattern
   this whole design exists to avoid.
6. Add every child to the same project as the parent (step 6's calls, once per child),
   then create the board:

   ```bash
   aiw project-board <owner>/<repo> <parent> --title "<parent title>"
   ```

   Best-effort — it always exits 0. A parent on no project, a closed project, or a
   missing `project` scope means no board and one warning line.
7. Return the parent URL, the child URLs in dependency order, and the board name. If
   `/run-issue` invoked this skill, hand control back to its Preflight step 3 with the
   **parent** issue number and continue the run — step 3.5 there will do its own
   `sub_issues` detection; the HARD RULE above no longer applies.
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
