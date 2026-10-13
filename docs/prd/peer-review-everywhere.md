# Peer review everywhere: design

Status: rev 3, approved by the workflow-critical reviewer; awaiting user approval.
As of 2026-10-13, on master 2321fd0.

## Problem

`/prd --review` runs a panel of single-lens reviewers (critical, CEO, CTO, security) next to the
worker, loops until critical approves, and asks the user when it can't settle a finding. Nothing
else has it. The user wants the same panel on other commands and on a free-form prompt, wants to
pick the lenses per run, and wants the reviewers (not the worker) on Opus.

## Decisions taken with the user

| # | Decision |
|---|---|
| D1 | Commands with the option: `/prd`, `/intake`, `/dump`, `/gh-issue`, and a custom prompt (New run's right-hand form). Excluded: `/run-issue` (has its own review), `/worklog`, `/day`, `/pr-review`, `/pr-grind`, `/pr-fix-comments`, `/issue-to-pr`. |
| D2 | One lens pool: critical, CEO, CTO, security, plus QA/testability, UX/design, performance. Each command offers only the lenses that fit it (P2); the custom prompt offers all seven. |
| D3 | Picking: per-lens checkboxes on New run (both forms) and a CLI flag per run. Ticking peer review starts with **critical only** ticked. |
| D4 | **Every selected lens blocks.** The loop runs until every selected lens approves, or the round cap (3, as today) is spent; then the user is asked (accept as known gaps / one more round / stop). |
| D5 | A finding that needs a fact or choice only the user has is asked (`needs_decision`), never guessed. |
| D6 | Disagreement: the worker may dismiss a blocking finding with a reason. If the same lens raises it again next round, the user decides. |
| D7 | Reviewers run on **Opus**, in subagents and in herdr tabs. The worker/dispatcher keeps its own model. `run-specialist`'s frontmatter stays `sonnet`, so `/run-issue`'s code-review specialists don't change. |
| D8 | The worker decides when to call the panel (a doc command reviews its draft before publishing; a custom prompt reviews when the work is done). |
| D9 | What a custom prompt's panel reviews: the code diff since the session started plus the worker's final answer, checked against the original prompt. |
| D10 | Terminal: a new `/ai-workflow:peer-review` you run after any work. Every reviewed command also takes `--herdr` (one tab per reviewer), as `/prd` does today. |
| D11 | `/prd` moves onto the shared mechanism. With only critical ticked it behaves as today; any other ticked lens now blocks too (D4). |
| D12 | Flow page: the PRD step's single "Peer review" box becomes lens checkboxes. The other Flow steps don't change. |
| D13 | Offer lists as in P2. |
| D14 | `/gh-issue` reviews the whole batch (every drafted body plus the epic parent) as one artifact, once every body is written and before the first `gh issue create`, so nothing reaches GitHub unreviewed. ("Preview" shows only titles, before any body exists, so the review sits after it.) Its post-create factchecker stays: it checks claims against the repo, the panel checks the drafts. |
| D15 | The panel runs only when the user invoked the command, so nothing is reviewed twice. A skill can't tell who invoked it, so this holds by construction: the panel runs only when `--review` is in the arguments, and programmatic callers (gh-issue step 0, run-issue's `/intake --whole`) never pass it. Tests pin that those call sites contain no `--review`. |
| D16 | Standalone `/peer-review` without `--since` asks one question: uncommitted only / since upstream (`@{u}`) / since a SHA you give. It never picks a start point silently. |

## Design

### P1. Engine: `prd_review.py` becomes `peer_review.py`, and `aiw prd-review` becomes `aiw peer-review`

The pure core (`validate`, `check_prior`, `decide`) already works on any text artifact. Changes:

- `next` takes `--artifact <file>` (was `--prd`), `--kind <prd|intake|dump|gh-issue|custom>` and
  `--lenses a,b,c` (default `peer_review.default_lenses`). Round 1 refuses a lens the kind
  doesn't offer, naming the offered set. `request.json` records the kind, the lenses and the
  rubric key (P2), so every later round uses the same panel and rubric.
- `decide` drops the per-lens `blocking` flag: every lens in the request blocks (D4).
  `advisory_blockers` goes away; `advisory` keeps the minor findings.
- `prd_sha256` becomes `artifact_sha256`.
- **Disputes (D6).** Every blocker/major finding must carry `"reraises": "<prior id>" | null`;
  `verdict` refuses it when the key is missing. `next` returns `{"action": "ask", "reason":
  "dispute"}` when a blocking finding's `reraises` names a prior finding of the same lens that
  the worker `dismissed`. A re-raised `fixed` finding (the fix didn't work) is a normal revise,
  bounded by the cap. The quote overlap is only a prompt for the reviewer, never a guess: if a
  blocker/major quote equals a dismissed prior quote from the same lens and `reraises` is null,
  `verdict` refuses with "same quote as dismissed <id>: set reraises, or say how it differs in
  distinct_because", and accepts it once `distinct_because` is non-empty.
- `aiw prd-review` is removed, not aliased (D11). Old dirs under `<data_dir>/prd-review/` are
  left alone; a `/prd` run that is mid-review across the upgrade can't resume (CHANGELOG says so).
- **One review dir per run, never reused.** This fixes an existing bug: today's dir is fixed per
  slug (`skills/prd/SKILL.md:164`) and `cmd_next` resumes from the highest existing round. So a
  second `/prd --review` on the same slug inherits the old run's rounds: it demands `--prior` for
  stale findings, or returns `ask`/`cap` with no review of the new draft. The new path is
  `<data_dir>/peer-review/<kind>/<run-id>/`. `<run-id>` is the aiw-ui session id for a
  UI-spawned session, and otherwise a run stamp (`<slug-or-"run">-<UTC yyyymmddThhmmssZ>`) the
  skill makes once with `aiw peer-review new <kind>` and reuses for every round. `next` resumes
  an existing dir only when given that dir; `new` never returns a dir that already exists.

### P2. Config: `prd_review` becomes `peer_review`

```json
"peer_review": {
  "max_rounds": 3,
  "default_lenses": ["critical"],
  "diff_max_lines": 3000,
  "rubric": {
    "doc":    "...today's rubric: a fix changes wording, never adds implementation...",
    "change": "...a fix may change code; a finding cites the Diff hunk or the Answer line..."
  },
  "lenses": { "critical": {...}, "ceo": {...}, "cto": {...}, "security": {...},
              "qa": {...}, "ux": {...}, "performance": {...} },
  "kinds": {
    "prd":      { "rubric": "doc",    "offer": ["critical","ceo","cto","security","qa","ux","performance"] },
    "intake":   { "rubric": "doc",    "offer": ["critical","ceo","cto","security","qa"] },
    "dump":     { "rubric": "doc",    "offer": ["critical","ceo","qa"] },
    "gh-issue": { "rubric": "doc",    "offer": ["critical","cto","security","qa","ux","performance"] },
    "custom":   { "rubric": "change", "offer": ["critical","ceo","cto","security","qa","ux","performance"] }
  }
}
```

Two rubrics, because today's rubric forbids implementation in a fix, and in a custom change a fix
*is* implementation. Each lens has one prompt that says "the artifact" instead of "this PRD", plus
one paragraph for a change artifact. No `.run-issue.json` override (D3 picks per run).

### P3. Artifacts

- **Doc kinds** (`prd`, `intake`, `dump`): the draft, written to `<review_dir>/draft.md` as `/prd`
  does today.
- **`gh-issue`** (D14): `<review_dir>/draft.md` holds every drafted body plus the parent, each
  under a `## Issue <n>: <title>` heading, reviewed before "Preview".
- **`custom`** (D9): `<review_dir>/artifact.md` with `## Ask`, `## Answer`, `## Diff`. Quotes are
  validated against this one file, so the quote rule works unchanged.
  - `## Ask`: in a UI session, the server writes `<review_dir>/ask.md` with the prompt verbatim
    when it spawns the session, and the worker copies it in. Standalone in the terminal, the
    worker lists the user's prompts from the session and asks the user to confirm them as the
    ask.
  - `## Diff`: built by `aiw peer-review diff --since <sha|@{u}>`, not by the worker, so the
    rules hold: `git diff <sha>` for tracked files, plus untracked files from
    `git ls-files --others --exclude-standard` only (honours .gitignore). A deny-list applies
    to tracked and untracked files alike (a committed `.env` is common): `.env*`, `*.pem`,
    `*.key`, `id_*`, `*.p12`, `*.keystore`, `*.sqlite*`, `*.db`, `credentials*.json`,
    `.npmrc`, `.pypirc`, and any filename containing `secret`. Binary files and lockfiles
    (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `composer.lock`, `poetry.lock`,
    `Cargo.lock`, `uv.lock`) are dropped too. The result is capped at `diff_max_lines`, ending
    with `truncated: <files>`, and the reviewers are told what was dropped or cut. `@{u}` with
    no upstream exits non-zero with a clear message; it never falls back silently.
  - After a fix round the worker rebuilds the file, which changes the hash and opens the next round.

### P4. One skill, `skills/peer-review/SKILL.md`, holds the loop

The loop moves out of `/prd` Step 5.5 into the skill. `/prd`, `/intake`, `/dump` and
`/gh-issue` each get one short line: "if `--review` and the user invoked this command (D15), run
the peer-review skill on <artifact> before <irreversible step>" (D8). The skill also runs
standalone (D10):

```
/ai-workflow:peer-review [--lenses critical,cto] [--since <sha>] [--herdr]
```

Standalone, it reviews the session's work as `custom` (P3). With no `--since` it asks (D16).

### P5. Opus (D7)

- Subagent: the skill dispatches `ai-workflow:run-specialist` with the Agent tool's
  `model: "opus"`, which takes precedence over the agent's `model: sonnet` frontmatter.
- herdr tab: `herdr agent start … -- --agent ai-workflow:run-specialist --model opus --disallowedTools …`,
  verified with the same `-p --verbose` init probe used for `--disallowedTools`, checking the
  init event's `model`.
- `run-specialist.md`'s "PRD mode" becomes "Peer review mode": it reads `peer_review.lenses.<lens>`
  and `peer_review.rubric.<request.rubric>`, and records with `aiw peer-review verdict`.
- The UI says the cost plainly: up to 7 lenses × 3 rounds on Opus.

### P6. CLI flag (D3)

`--review` alone means the default lenses (critical). `--review critical,cto,qa` picks lenses.
The commands' argument parsing reads the token after `--review` as a list only if it doesn't
start with `--`, so `--review --herdr` is "default lenses, in herdr". `aiw peer-review next`
rejects unknown and not-offered lenses.

### P7. Web UI (D1, D3, D12)

- New run, left form: for `prd`, `intake`, `dump` and `gh-issue`, a "Peer review" checkbox; when
  ticked, one checkbox per offered lens (critical pre-ticked), with the copy "each ticked
  reviewer must approve; up to 3 rounds on Opus". The body sends `peer_review: ["critical", …]`
  instead of today's `true` (the UI is the only client, so `true` is dropped). The server
  appends `--review <list>` and rejects a lens the command doesn't offer.
- New run, right form (custom): the same, with all seven. The server records HEAD at spawn,
  writes `ask.md` (P3), and appends one line to the prompt:
  `When the work is done, run the ai-workflow:peer-review skill with --lenses <list> --since <sha>.`
- The offer lists come from config through the existing options endpoint, so the UI never
  hardcodes them.
- **Post-check for custom sessions** (the line is not a gate): when the session ends, the
  server reads the round state in `<data_dir>/peer-review/custom/<session-id>/`, never just
  whether the dir exists (it always does, because `ask.md` is written at spawn). No
  `round-1/request.json` → "not run"; the last `next` decided `done` → "approved"; it decided
  `cap` → "stopped at cap"; rounds but no final decision → "unfinished". `next` records each
  decision in `round-<n>/decision.json` so the server doesn't have to recompute it.
- Flow page: the PRD step's box becomes the same lens picker. In Flow auto mode, a cap still
  stops the flow, as today.
- Headless sessions ignore `--herdr` and use subagents; decision, dispute and cap questions go
  through `aiw ask`.

### P8. Docs and tests

- REFERENCE (`aiw peer-review next|verdict|diff`, flags), HOW-IT-WORKS, CONTEXT ("PRD peer
  review" → "peer review"; define "lens pool", "offered lenses", "dispute"), CHANGELOG
  (including the mid-review upgrade break).
- `test_prd_review.py` → `test_peer_review.py`: a second run on the same slug starts at round 1; `new` never reuses a dir; every lens blocks; offer check; rubric by kind
  (a custom request carries `change`); `reraises` missing → refused; reraises a dismissed
  finding → dispute; reraises a fixed finding → revise; same quote, null, no reason → refused;
  same quote with `distinct_because` → accepted; `diff` drops `.env`, lockfiles and binaries,
  and truncates with a note; the deny-list hits a tracked `.env`; `@{u}` with no upstream exits non-zero; existing quote/prior tests ported.
- `test_scripts.py` pins for `/prd` Step 5.5 and `run-specialist` updated.
- Pins that gh-issue step 0 and run-issue's `/intake --whole` calls contain no `--review` (D15).
- UI: lens picker and body shape in `test_ui_static.py`; `ui_repos` tests for the appended
  flags/line, the not-offered rejection, `ask.md` and the start sha; the post-check badge's
  four states.

## Delivery

Stacked PRs. Each one is shippable on its own and is sent to the reviewer before it opens.

1. **Engine + config + every caller renamed:** P1 (including the one-dir-per-run fix), P2, P6's engine side, the `new` and `diff` subcommands,
   run-specialist's Peer review mode, `/prd` Step 5.5 switched to `aiw peer-review` (still in
   the prd skill), route.py usage, REFERENCE, CONTEXT, pins. `/prd --review` keeps working.
2. **The skill:** `skills/peer-review`, the loop moved out of `/prd`, the custom artifact,
   `--since`, Opus (subagent + verified herdr), and the `/intake`, `/dump`, `/gh-issue` hooks
   with the D14/D15 rules.
3. **UI:** New run (both forms), Flow PRD step, `ask.md` + start sha, and the post-check badge.
