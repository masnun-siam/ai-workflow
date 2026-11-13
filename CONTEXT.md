# setu

Local frontend for Claude Code that drives the blubird plugin. This is the vocabulary used in code, UI and docs.

## Language

**Product**:
A Documentation Repo plus the code repos listed in its `.blubird/repos.json`. setu groups boards, inbox and River by product. Registered in `~/.setu/products.json`.

**Documentation Repo**:
The repo holding `docs/prds/` for a product. `docs`-run steps (`create-prd`, `create-tasks`, `map-prds`, `security-sweep`, `project-coordinator`) run in its checkout.

**PRD**:
The product requirements for one feature, at `docs/prds/<slug>.md`, written by blubird `create-prd`. Status Draft, In review or Approved; only Approved is split into tasks.

**Epic / refined issue**:
An epic is the parent GitHub issue of one PRD entry; its child issues become refined issues once `refine-issues` writes their body. Only a refined issue is ready to implement.

**River**:
The home screen: the pipeline as columns of cards, one per stage. Also one of the three looks (Classic, Console, River).

**Stage**:
A column of the River and the group a step belongs to: `prd`, `tasks`, `refine`, `implement`, `review`, `release`, `notify`, `ops`. Each registry step names its stage.

**Step**:
One entry of the built-in registry (`create-prd`, `implement-issue`, `pr-grind`, `release-pr` ...). A step is either a blubird skill (`/blubird:<skill>`) or a setu built-in prompt, and declares where it runs (`runs_in`: `docs`, `repo`, `issue` or `none`).

**Session**:
One headless `claude -p` run started by setu, kept in `~/.setu/sessions/<id>/` with `meta.json`, `stream.jsonl` and `stderr.log`. Status: starting, running, waiting, limited, queued, done, failed, stopped. A `waiting` session has asked the human a question through `setu ask`.

**Idle guard / stalled**:
The idle guard is setu's Claude Code `Stop` hook (`setu hook idle`) on headless skill sessions: it blocks a turn that ends without a ✅ table, a `setu ask` question or live background work, at most twice in a row. A session it then lets end is **stalled** (`stalled` on its record): it ended without finishing or asking.

**Round**:
One batch of questions a waiting session asks, answered together from the Inbox, the session page or Away mode.

**Account**:
A `claude` command (config dir) sessions run under. Usage meters and limit auto-resume are per account.

**Inbox item**:
Anything waiting on the human, derived on every read (never stored): a waiting session, a PR ready to review, a stuck lane, a paused grind, a release to approve, a needs-cleanup merge. Each carries server-built actions.

**Action**:
A server-built button on an item: key, label, method, path. The UI runs it as given and has no per-type logic.

**Lane**:
One issue run by Dispatch: queued, implementing, grinding, merge_gate, conflict_fix, awaiting_merge, followups, closed or skipped. A lane owns its issue; manual starts on it are refused.

**Dispatch**:
setu's own parallel runner: an epic's child issues become lanes, each a `blubird:implement-issue` session followed by a grind. Stored in `~/.setu/dispatches/<id>.json`.

**Coordinator**:
blubird's `project-coordinator`, which runs up to 5 interactive sessions as terminal panes. setu starts it and only reads its runs and claims under `~/.claude/project-coordinator/`.

**Grind**:
The loop that takes a PR from draft to merge-ready: wait for reviewers, fix or rebut each finding, re-run CI, repeat. Modes `deep` or `simple`. State is `~/.setu/pr-grind/<owner>-<repo>-<pr>.md`, mutated only through `setu grind ...`.

**Peer review**:
A panel of read-only reviewer sessions, one per lens, that review an artifact in rounds. State under `~/.setu/peer-review/`.

**Release flow**:
`cut` (the `release-pr` prompt opens the head-to-base PR) → `grind` → `merge` → `notify` (setu posts the release note once) → `done`. A dry run stops after the PR draft.

**Away mode**:
A switch (`afk.json`) for when the human is gone. Waiting rounds go to the read-only away answerer, which answers only what it is confident about and holds the rest; stuck lanes are retried.

**Built-in prompt**:
A prompt embedded in the binary (`prompts/`): `release-pr`, `pr-grind`, `release-note`, `peer-review`, plus the agent bodies `peer-reviewer` and `away-answerer`. Extracted to `~/.setu/prompts/<version>/`.

**blubird**:
The Claude Code plugin that carries the team's dev process as skills. setu detects, installs and updates it, and never copies its skills.

**Look / Mode / Layout**:
The three appearance settings: Look (Classic, Console or River), Mode (System, Dark, Light), Layout (Rail + drawer, Tabs + split).

**Data dir**:
`~/.setu` (override `SETU_HOME`). Holds setu's own state only; GitHub and `docs/prds/` are the truth.
