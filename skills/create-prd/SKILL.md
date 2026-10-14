---
name: create-prd
description: "Turn a feature idea into a product requirements document with its technical design, every decision settled by interviewing the user, and on approval one GitHub epic per `## Epics` entry: scan the codebase first, grill the user, then save the PRD to the repo's docs/prds/, the Obsidian vault and/or the repo's GitHub wiki. Use whenever the user says /create-prd, 'write a PRD', 'PRD for X', 'product requirements for X', 'approve the PRD', 'flesh out this feature before we build it', or hands over a feature idea, BRD file, Obsidian note or issue URL and wants it pinned down as a PRD. Not for raw capture/filing (use /dump), breaking a PRD into tasks (use /create-tasks), or normalising input only (use /intake)."
allowed-tools:
  - Bash
  - Read
  - Write
  - Grep
  - Glob
  - Agent
  - Skill
  - AskUserQuestion
---

# /create-prd — Requirement → grilled PRD → saved → approved with its epics

Produces the source of truth for a feature: what it does, why, and how it is built. The task list and every issue are derived from it, so a question left open here comes back in the middle of implementation and can change issues that are already in progress. The aim is a PRD that leaves nothing to ask.

Why this order matters: scanning before interviewing means the questions are informed ("the code already does X — do you want that kept?") instead of asking the user things the repo can answer. Showing the full draft before saving matters because two of the three destinations (vault, wiki) are shared and hard to retract.

> **Paths.** This skill runs in the user's repo, not the plugin's. Run `aiw paths` and use its
> `plugin_root` value for `<plugin_root>` below; never guess a path. If `aiw paths` does not print
> JSON whose first key is `plugin_root`, stop and report that the plugin is not installed.

`<skill_dir>` is `<plugin_root>/skills/create-prd`. **Templates:** use the repo's own
`docs/templates/prd.md` and `docs/templates/epic.md` when they exist; otherwise
`<skill_dir>/templates/prd.md` and `<skill_dir>/templates/epic.md`. "The PRD template" and "the
epic template" below mean the resolved file.

## Arguments

`/create-prd <requirement | feature-folder> [--to local,obsidian,wiki] [--review [<lens,lens>] [--herdr]]`
`/create-prd --update <prd-path> <decisions>` (see **Update mode**)
`/create-prd approve <prd-path | slug>` (see **Approve**)

- `<requirement>`: free text, a BRD file, an Obsidian note, a Sentry link or a GitHub issue URL.
- A legacy `docs/prd/<slug>.md` path is not a requirement: it is the existing PRD, handled as Step 2 says.
- `<feature-folder>`: a vault path `05-Work/<Project>/<Feature>` that holds a `Dump.md` (as left by `/dump`). `/create-prd` fills that folder's seeded `PRD.md`.
- `--review [<lens,lens>]`: before the Step 6 review gate, a reviewer panel checks the draft until
  every picked lens approves (see **Step 5.5: Peer review**). The token after `--review` is a lens
  list only if it doesn't start with `--`, so `--review --herdr` means the default lens (critical). `--herdr` (terminal only) gives each reviewer its own herdr tab
  you can watch and talk to.
- `--to`: one or more destinations. Default `local,obsidian`, and nothing is asked about other destinations: `wiki` is written only when named here. The repo's `docs/prds/<slug>.md` (`local`) is the canonical copy; the Obsidian `PRD.md` is a mirror of it. If the Obsidian project can't be resolved (Step 2), ask which project to use and offer `local` instead; never leave the run with no destination.

### Asking the user

A headless run (started from the workflow UI) has no terminal to answer in, so
`AskUserQuestion` is not available there. You are headless when your system prompt contains
`Headless run: ask via aiw ask`. At every question below, the same header, question and options
are used either way; only the transport differs.

- **Headless:** call the command below. Use the quoted heredoc: question text may embed arbitrary
  text, so never put it inside single quotes on the command line. Starts with `aiw `.

  ```
  # one call per round
  aiw ask <<'EOF'
  {"questions":[{"header":"...","question":"...","multiSelect":false,"options":[{"label":"...","description":"..."}]}]}
  EOF
  ```

  Any other stop-and-ask in this skill also goes through `aiw ask` when headless, never prose. List the recommended option first with `(Recommended)` on its label. Free text is
  always allowed. Then end your turn immediately and do nothing else; the answer arrives as
  your next message, `Answer to q-...: {"0":{"labels":["..."]}}` or
  `{"0":{"other":"free text"}}`. Strip any ` (Recommended)` suffix from the label and take
  the same branch the interactive answer would. Free text that names no option is feedback for
  that question, never an approval.
- **Otherwise:** not headless, so skip `aiw ask` and call AskUserQuestion exactly as written at the question.

### Flow auto mode

When the system prompt contains `Flow auto mode`, this run is the PRD step of the aiw ui guided
Flow. The user answers grilling questions and nothing else, and the next steps (`/create-tasks`,
`/refine-issues`) will ask nothing at all, so this interview is the only chance to settle anything. Changes:

- **Grilling (Step 4)** also covers what an issue would otherwise be grilled on: acceptance criteria
  for every requirement, priority, affected users, and every corner case (empty/null input,
  concurrency, permissions, error and failure paths, boundary values, existing-data migration).
  Add these as branches of the starting tree.
- **Open questions must be empty.** Before Step 6, if the draft's `## Open questions` lists
  anything, keep grilling on exactly those items until none remain; only implementation choices
  meant for the later technical spec may stay, and each must say so.
- **Peer review decisions (Step 5.5)**, with `--review`, are asked like grilling questions: they
  are the only other questions, because this step is the last chance to settle anything. A
  cap-reached block stops the flow here (Step 5.5, item 4).
- **No other question is asked.** Existing PRD (Step 2): update it in place. No matching
  project (Step 2): use the project and feature folder from the input path, creating the feature
  folder if needed. Destinations: `local` and Obsidian, whatever `--to` says. Review gate (Step 6):
  approved automatically once Open questions is empty. The wiki is never pushed.
- **Status:** saved as `Draft`; the Flow's Tasks step approves it (see `/create-tasks` Flow auto mode).
- Report the destination path in Step 8 as usual; the `→ next:` line is unchanged.

## Step 1: Normalise the input

A vault feature folder (`05-Work/<Project>/<Feature>`) that contains `Dump.md` → read `Dump.md` and `PRD.md` with `obsidian vault=notes read` and use both as the requirement; take the project and feature from the path (skip the folder resolution at the end of Step 2). Free text → use as is. Anything else (file path, Obsidian note, URL) → run `/intake` on it and use its brief as the requirement. Don't re-implement parsing here.

Derive a short **title** and kebab-case **slug** from the requirement. Detect the repo with `gh repo view --json nameWithOwner,name` (fall back to the git remote). If the working directory is not inside a git repo (`git rev-parse --show-toplevel` fails), drop `local` from the destinations, write Obsidian only, and say so in Step 8.

## Step 2: Check for an existing PRD at every chosen destination — before any interviewing

Interviewing for ten minutes and then discovering a PRD already exists wastes the user's time, so check first.

| Destination | Existence check |
|---|---|
| local | `docs/prds/<slug>.md` in the repo root, then the legacy `docs/prd/<slug>.md` |
| obsidian | `obsidian vault=notes file path="05-Work/<Project>/<Feature>/PRD.md"` — prints `Error: ... not found` (exit code 0) when missing, so read the output text |
| wiki | after cloning (Step 7), look for `PRD-<Title-With-Dashes>.md`; for an early check use `git ls-remote` only to confirm the wiki exists, and defer the page check to the clone |

Exception: an Obsidian `PRD.md` with frontmatter `status: seed` is the input, not a collision — continue without asking and fill that same file. Read the status with `obsidian vault=notes property:read path="05-Work/<Project>/<Feature>/PRD.md" name=status` (the existence check above does not show frontmatter); only output that is exactly `seed` counts. Anything else (another value, empty output, an error) means any other existing PRD, including finished PRDs and ones seeded before the marker existed, and still stops here.

If a PRD already exists anywhere: **stop and ask the user** (headless: `aiw ask`, then end your turn) what to do (read it and update it, pick a new name, skip that destination). Never overwrite silently. If they choose to update, read the existing PRD before Step 4 so the interview builds on it and keeps earlier decisions. When its status is `Approved`, the update follows **Changing an approved PRD**; an update reached from here is interactive, so it still ends with Step 8's `→ next: /create-tasks <prd-path>` line. When both a repo copy and a vault copy exist, read the repo copy: it is canonical, and Step 7 rewrites the vault copy as its mirror. Find the pair through the links Step 7 records (the repo copy's `**Mirror:**` line, the vault note's `canonical` property), never by matching names.

A legacy `docs/prd/<slug>.md` is the existing PRD. Offer to move it (ask; in Flow auto mode, just do it and say so) with `git mv docs/prd/<slug>.md docs/prds/<slug>.md`, then carry on with it at its new path. Declined: work on it where it is and say that `/create-tasks` reads only `docs/prds/`.

For Obsidian, also resolve the project and feature folder here, the same way `dump` does:

1. `obsidian vault=notes read path="05-Work/Index.md"` and match the repo/project name against it (e.g. acme-api → `05-Work/Acme`). Read `05-Work/<Project>/Index.md` too.
2. Show the resolved target in the Step 6 confirmation. A **new** feature folder needs the user's explicit OK, same rule as `/dump`; never create a project folder or edit `05-Work/Index.md` on your own.
3. If no `05-Work/<Project>` entry matches, **stop and ask** (headless: `aiw ask`, then end your turn): which existing project to use, or write to `local` instead. Do not guess and do not create one.

## Step 3: Scan the codebase (once, up front)

Launch one Explore agent with the requirement and ask for: the modules, models, routes/jobs and UI that relate to it; current behaviour the requirement touches or contradicts; existing constraints (limits, permissions, tenancy, billing, integrations); similar features worth reusing, and the closest existing feature that sets the pattern to follow; overlap with existing PRDs (`docs/prds/`) and open issues; and whether another service in the repo writes the same data. Ask for file paths and a short summary, not file dumps.

Follow the repo's own search rules if its CLAUDE.md names a preferred code-search tool (e.g. GitNexus) — put that in the agent prompt. Keep the summary as interview context: it is what makes the questions and recommendations sound, and it is not copied into the PRD. Only the Overview's "Today:" list draws on it.

## Step 4: Grill

Invoke the `grilling` skill via the Skill tool, passing the requirement, the scan summary and the starting design tree below. Let grilling run its own rounds and its own rule about facts vs decisions: when a question needs a fact from the code, look it up (sub-agent) instead of asking the user. The interview ends only when the user confirms shared understanding. Headless, the interview is the same but every round goes through `aiw ask`, then end your turn: one `aiw ask` per grilling round, one question per numbered question (header `Q<n>`, `multiSelect` false), options are the choices the question names with the recommended first, and a question naming no choices carries its recommended answer as the single option.

Starting tree. Each branch unlocks the ones below it, so ask the top ones first:

1. **Problem and users** — who has the problem, what happens today, why now; the roles involved and what each may do.
2. **Goals and non-goals** — what done looks like; what is deliberately excluded from this version.
3. **Requirements** — each behaviour as something testable, with acceptance criteria, limits and validation rules. Reconcile against what the scan found.
4. **Edge cases** — concurrency, empty states, limits reached, existing data, failure paths; and data isolation **only when the repo is multi-tenant** (its CLAUDE.md or the code says so).
5. **Technical design** — which store and the shape of the data, the API contract, sync or queued, realtime events or other services that read or write the same data, migration of existing data, and how each requirement is tested.
6. **Rollout and cost** — all users at once or gated, billing or provider-cost impact, priority, success metrics.
7. **Epics** — how many (one unless the user wants more), and which requirements each covers.

Skip branches the requirement already settles.

## Step 5: Draft

Fill the PRD template with what was agreed, in plain language. Keep the user's decisions and their one-line reasons in **Decisions**; anything still unresolved goes in **Open questions** (never invent an answer to fill a section — write "None" if empty).

- Requirements are numbered `FR-n`, each with an acceptance line that someone could test. They describe behaviour.
- "Technical design" records the decisions about how each requirement is built and names the `FR-n` it serves. The API contract is exact enough for the frontend to be built against it before the backend is merged.
- **Decisions, not code.** Keep the PRD at the level of contracts and behaviour: data shape, endpoints and their fields, what each part is responsible for, how it behaves under concurrency and failure. Leave out file paths, class and method names, signatures, step-by-step logic, query keys, styling classes, test file names and line numbers. They are noise to a reviewer, go stale as the base branch moves, and are worked out by `/refine-issues` against the current code. Describe existing code by what it does ("notes are capped at 12 per conversation"), not by where it lives.
- **Use diagrams.** The team reads and discusses a PRD more easily with pictures beside the text. Add a Mermaid diagram wherever one is clearer than prose, and always for a big feature: a flowchart for a user flow, a sequence diagram for an exchange between parts or a race between two requests, a state diagram for a lifecycle, an entity diagram for the data. Place each next to the text it supports with a one-line caption. A diagram never replaces a requirement or its acceptance line, and a small change needs none.
- Every answer from the interview goes under "Decisions" with its reason.
- "Edge cases" always covers concurrency, empty states, limits reached, data isolation when the repo is multi-tenant, and existing data.
- Non-goals are specific enough that nobody builds them by accident.
- "Epics" lists one epic unless the user asked for more, each with the `FR-n` it covers, as `- **E<n> <title>** — covers FR-a to FR-b. Issue: —` (Approve fills the number).

The header's `**Status:**` is `Draft`, `In review` or `Approved`; a new PRD starts `Draft`. The Obsidian copy additionally gets tag frontmatter and full-path wikilinks in `## Related` (Step 7). Local and wiki copies use plain links.

### Step 5.1: Check it before showing it

- Could a tester write a test from each acceptance line alone?
- Could an engineer start any part of the technical design without asking a question? If not, go back to Step 4.
- Is "Open questions" empty? If an answer needs someone who is not in the session, leave the question there with that person's name and keep the status `Draft`.
- Is every codebase claim backed by a path you opened in this session?
- Does it name a file, class, method or line number, or spell out logic step by step? Take it out unless the name is part of a contract (an endpoint, a field, a table or collection, a command operations must run).
- Is there a flow, lifecycle, data model or race that takes a paragraph to explain? Give it a diagram, and check each diagram agrees with the text beside it.
- When the repo is multi-tenant, is data isolation stated, not assumed?
- Does anything contradict a principle in the repo's `CLAUDE.md` or a convention in its docs?

## Step 5.5: Peer review (only with `--review`)

A panel of single-lens reviewers checks the draft; the loop lives in the `ai-workflow:peer-review`
skill. The user picks the lenses with `--review <lens,lens>` from those `/create-prd` offers
(`peer_review.kinds.create-prd` in `<config>`, from `aiw paths`); bare `--review` runs the default
(critical). **Every picked lens blocks.**

1. `aiw peer-review new create-prd --slug <owner>-<repo>-<slug>` prints `<review_dir>`, a fresh
   directory for this run; never reuse one from an earlier run.
2. Write the draft to `<review_dir>/draft.md` with the Write tool; it lives outside the repo.
3. Invoke the `ai-workflow:peer-review` skill with
   `--kind create-prd --dir <review_dir> --lenses <picked>` (plus `--herdr` if given). It edits
   `draft.md` in place, asks the user the decisions and disputes, and records rulings in its
   `## Decisions`.
4. Read its finish line. **`stopped`**: save nothing. **`known gaps accepted`**: add each gap under
   the draft's `## Open questions`. In Flow auto mode a cap stops here, as the skill says: the run
   never accepts gaps on the user's behalf.

Step 6 then shows `draft.md` and, above it, the skill's summary: the lenses picked, the rounds
run, each lens's last verdict, each advisory finding with its disposition, the decisions
recorded, and any known gaps.

## Step 6: Review gate — always

Show the **full** draft (if headless, put the draft in the question text and use `aiw ask` with options `Approve (Recommended)` / `Edit`, edits as free text, then end your turn), plus for each chosen destination the exact path it will be written to (and, for Obsidian, the resolved project/feature folder and whether it is new). Wait for an explicit OK. Apply any edits and show the changed draft again until the user approves.

Nothing is written anywhere before this approval. The wiki push needs its own explicit confirmation in Step 7, because pushing to a wiki publishes it. This gate approves the draft for saving; it does not set `**Status:** Approved` (see **Approve**).

## Step 7: Save

**local** — the canonical copy. Write `docs/prds/<slug>.md` with the Write tool (create `docs/prds/` if needed). Its `**Mirror:**` line names the vault `PRD.md`; drop the line when Obsidian is not written. Don't commit or push; the user decides. When the user opens a PR for it, set `**Status:** In review`.

**obsidian** — the mirror: the same PRD as the local copy, plus the tags and wikilinks below. Always through the `obsidian` CLI with `vault=notes`, never plain file writes, so the index stays in sync. Follow `skills/dump/SKILL.md` ("Tagging and linking" and "New feature") for the exact commands:

```
obsidian vault=notes create path="05-Work/<Project>/<Feature>/PRD.md" content="<PRD>"
obsidian vault=notes property:set path="05-Work/<Project>/<Feature>/PRD.md" name=tags value="work,<project-tag>,type/feature,<feature-slug>" type=list
obsidian vault=notes append path="05-Work/<Project>/<Feature>/PRD.md" content="\n## Related\n- [[05-Work/<Project>/Index|<Project> Project Index]]"
obsidian vault=notes append path="05-Work/<Project>/Index.md" content="- [[05-Work/<Project>/<Feature>/PRD|<Feature>]]"
```

If the target was a seed (Step 2): replace the `create` line above with `obsidian vault=notes create path="05-Work/<Project>/<Feature>/PRD.md" content="<PRD>" overwrite`, skip the project-index `append` (`/dump` already added it), and after the `tags` line run `obsidian vault=notes property:set path="05-Work/<Project>/<Feature>/PRD.md" name=status value=draft`. Overwriting re-creates the file, so keep the `tags` and `## Related` lines; the `## Related` block must list `Dump` again (see the next paragraph).

Every `overwrite` here replaces the whole note. If a read of a file you know exists fails or
comes back empty (vault not open, wrong path), stop and report: never overwrite with partial content.
An overwrite also drops the note's frontmatter. So read the note's `tags`, `status` and
`canonical` properties before any overwrite, and re-run `property:set` for each of them right
after it; never rely on the content to carry frontmatter.

When `local` was also written, link the mirror back to it, after the `create` (or `create ... overwrite`) and never before it:
`obsidian vault=notes property:set path="05-Work/<Project>/<Feature>/PRD.md" name=canonical value="<owner/repo>:docs/prds/<slug>.md"`.

Read a sibling's tags first to reuse the feature slug, and list existing siblings (Dump, Decisions, SRS…) in `## Related`. Add the PRD line to existing siblings' Related blocks as dump does. The project tag table lives in dump's SKILL.md.

**wiki** — only after a final "push to the wiki?" confirmation (if headless, `aiw ask` it, then end your turn):

1. `git clone --depth 1 https://github.com/<owner>/<repo>.wiki.git` into the scratchpad directory (the wiki's default branch is usually `master`; check with `git branch --show-current`).
2. Write `PRD-<Title-With-Dashes>.md`. Stop and ask if it already exists.
3. Add a link to it on a `PRDs` index page (create `PRDs.md` if missing) and, if the wiki has `_Sidebar.md`, leave it alone unless the user asks.
4. Commit with a plain message (`docs: add PRD — <Title>`) and push. Never use `--no-verify`.

If any save step fails, report which destinations succeeded and which didn't. Don't retry silently.

## Step 8: Report and hand off

One line per destination with its final path or URL. End with the line `→ next: /create-tasks <prd-path>`, where `<prd-path>` is the Obsidian `PRD.md` path, or the first written destination when Obsidian was not written. The guided Flow opens that path as a vault note; whoever reads it follows its `canonical` property to the repo copy. It is the last line of your output; the Guided Flow parses it. Do nothing further.

## Approve

`/create-prd approve <prd-path | slug>` runs when the user says the team has reviewed the PRD.
Approval is the user's call, never yours. A slug resolves to `docs/prds/<slug>.md`.

1. Resolve the canonical copy by the **Update mode** rules (a slug may also find a legacy
   `docs/prd/<slug>.md`: offer the Step 2 move first), and fold in any review changes the
   user names.
2. Refuse while `## Open questions` has an entry, and say which ones; resolve those first. A
   section that reads only `None` is empty.
3. For each `## Epics` entry whose `Issue:` is `—`, draft an epic from the epic template.
   - **Re-run safety** first: `gh issue list --label epic --label prd-<slug> --state all --json number,title`.
     Reuse an existing epic with the same title instead of drafting a new one.
   - **Labels.** Ensure the label once, without touching a repo's own `epic` label (`--force` would recolour it):
     run `gh label list --search epic --json name --jq '.[].name'`, and only when no line is exactly
     `epic`, run `gh label create epic --color 0E8A16 --description "parent of a task list"`. A
     failure here stops the run with gh's error. Ensure `prd-<slug>` exists the same way
     (`gh label list --search prd-<slug> …`, create it only when no line is exactly `prd-<slug>`).
   - **Project.** Never hard-code a project name or number; read it from where the team's issues already are:
     1. List the projects recent issues sit on: `gh issue list --state all --limit 50 --json number,projectItems`. Look at epics first (`--label epic`), then at all issues.
     2. One project in use: add the new issues to it with `gh issue create --project "<title>"`, or `gh issue edit <n> --add-project "<title>"`.
     3. More than one in use: ask which, recommending the one the most recent issues of the same kind are on.
     4. None in use: check `gh project list --owner <owner>`. Propose a project if exactly one is open; otherwise skip the project step and say so in the report. Do not create a project.

     Project commands need the `project` scope on the `gh` token (`gh auth refresh -s project`). If it is missing, say so and carry on without the project step instead of failing.
4. Show each epic's title, labels and project, and ask (AskUserQuestion, headless: `aiw ask`, then end your turn) with the options "Create these epics (Recommended)" / "Stop". Create nothing without the yes: Stop leaves the status unchanged. **Flow auto mode, or `/flow` calling approve after its checkpoint, skips this question**, because the user already confirmed.
5. For each new epic: `gh issue create --title "Epic: <title>" --label "epic,prd-<slug>" --body-file <file>` (plus `--project "<title>"` when step 3 found one), the body written to a scratch file with the Write tool.
6. Write `Issue: #<n>` back into each `## Epics` line, in the canonical copy and then the mirror.
7. Only now set `**Status:** Approved` in the canonical copy, and run
   `obsidian vault=notes property:set path="<mirror>" name=status value=approved` on the mirror
   when one exists (keep its content in step with the canonical copy, by the Step 7 rules).
8. Report each epic's number and URL, and any reused. The last line is `→ next: /create-tasks <prd-path>`.

## Update mode

`/create-prd --update <prd-path> <decisions>` records decisions made after the PRD was written. A
later step, such as task refinement, may settle questions the interview missed, and those answers
belong in the PRD. `<decisions>` is one line per decision: `<decision> — <why> (<source>)`, where
the source is the issue or task that raised it.

`<prd-path>` is either copy. Resolve the canonical one first:

- A repo `docs/prds/<slug>.md`: it is canonical. Its `**Mirror:**` line names the vault copy.
- A vault `PRD.md` with a `canonical` property (`obsidian vault=notes property:read ... name=canonical`)
  naming this repo: edit that repo copy as canonical, and this note as its mirror.
- A vault `PRD.md` with no `canonical` property, or one naming another repo: edit the vault
  copy alone and report "no canonical copy". Never create a repo file during an update.

There is no grilling, no codebase scan and no review gate here: the user already answered each
question where it came up. For each decision:

1. Read the PRD. If `## Decisions` already records it (same meaning, not just the same words),
   skip it; it is already there.
2. Otherwise append `- <decision> — <why> (<source>)` to `## Decisions`.
3. If it answers an item in `## Open questions`, remove that item. If it changes a requirement or
   its acceptance check, edit that requirement to match.
4. When the PRD is `Approved`, also append `- YYYY-MM-DD — <decision>; issues affected: <list or none>`
   to `## Change log`, and tell the user which tasks and issues must change. Never edit an issue here.

Write the canonical copy back, then apply the same edits to the Obsidian mirror when one exists
(read it, edit it, write it back with `obsidian vault=notes create ... overwrite`, keeping its
tags and `## Related`; the Step 7 rules apply: never overwrite with partial content, and re-set
`tags`, `status` and `canonical` after the overwrite). Report which decisions were added and which were already there, and every requirement or acceptance check you edited as before → after, so no requirement changes without someone seeing it. Called explicitly as `/create-prd --update`, print no
next line: the calling command owns what happens next. An update reached from Step 2 (an
interactive run on an existing PRD) ends with Step 8's next line instead.

## Changing an approved PRD

A decision that changes after approval is changed here first, never only in an issue or a pull request. Update the affected sections through **Update mode**, which adds a `## Change log` line with the date, the reason and the issues affected, then tell the user which tasks and issues must be updated to match. Ask before editing any issue. Reached from Step 2, finish with Step 8: its last line is `→ next: /create-tasks <prd-path>`, so `/create-tasks` revises the task list.

## Stop and ask when

- The request is a solution with no stated problem.
- Two requirements conflict, or one conflicts with a data-isolation or billing rule.
- The feature needs something the product does not have at all (a new provider, a new role, a new data store).
- The technical design needs a new dependency or a pattern the repo's CLAUDE.md or docs do not describe.

## Improve this skill

Each use of this skill is also a test of it.

- **While working**, note privately any step here that was wrong, outdated, missing, unclear or unnecessary, and anything the user had to explain or correct that this file could have said.
- **Before you finish**, keep only findings backed by what happened in this session that would recur for the next person. Facts about the user's repo go to its `tasks/lessons.md`, not here.
- **If anything is left**, tell the user what happened and ask (AskUserQuestion, headless: `aiw ask`) whether to file it, recommended option first. On yes, resolve `<plugin_repo>` from the `repository` (else `homepage`) field of `<plugin_root>/.claude-plugin/plugin.json`, falling back to `masnun-siam/ai-workflow`, and run `gh issue create --repo <plugin_repo> --title "skill(create-prd): <what to change>" --body-file <file>` with what happened and the exact proposed edit as a diff.
- **Never edit this skill file**, even when the plugin root is a git checkout. Never propose an edit that weakens a gate.

## Guardrails

- No customer PII, secrets or production data in the PRD. If the interview surfaces any, refer to it generically.
- The PRD is a deliverable for the user. Don't add session URLs, local absolute paths or "Claude-Session" lines to it.
- Don't commit or push the repo; the only push this skill ever performs is the confirmed wiki push.

## Self-improve

After the task, follow `../../self-improve.md` (relative to this skill's directory).
