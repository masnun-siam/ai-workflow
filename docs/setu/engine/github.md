# GitHub + pipeline engine: behavioural spec for the Go rewrite

Source: `run-engine/` (Python, stdlib only). Everything here is read from the code and pinned by `test_ui_poller.py`, `test_ui_inbox.py`, `test_ui_bootstrap.py`, `test_ui_products.py`, `test_ui_mergeclean.py`, `test_threads_ci.py`, `test_ui_delivery.py`, `test_ui_planning.py`. Python names are given only to locate behaviour.

Conventions: "data dir" = `$CLAUDE_PLUGIN_DATA` or `~/.claude/plugins/data/ai-workflow` (setu will pick its own; keep it outside the repo). "slug" = `owner/name`, compared case-insensitively everywhere, stored in the registered spelling. Every `gh` call is an argv list (no shell); `gh` is the only GitHub client (no tokens handled by the engine). The engine never writes to GitHub from the poller/board code (read-only); writes happen in skills (`gh issue edit`, `set-status.sh`) and in `aiw threads resolve`.

Shared helpers to port:
- `run(argv, cwd, timeout)`: never raises. Missing binary -> rc 127, stderr = error text. Timeout -> rc 124, stderr `timed out after {n}s`.
- `gh_json(args, cwd, timeout=120)` -> (value, proc). Non-zero rc -> value None. Else parse stdout as JSON; if it is not JSON (a bare `--jq` scalar) return the stripped string; empty -> null.
- `atomic_write_text`: temp file in same dir, fsync, rename. `json_lock(path)`: exclusive flock on `<path>.lock` around read-modify-write. `backup_if_corrupt(path)`: a present-but-unparsable or non-object JSON file is renamed `<path>.corrupt-<unix>` before the next write.
- `supervised_loop(tick, interval)`: daemon goroutine; a panic/err in `tick` is logged, never fatal; sleep `interval` after each tick.

---

## 1. `gh` calls (complete inventory)

### 1.1 Board poller (`ui_poller.py`) - GraphQL via `gh api graphql -f query=<Q> -F owner=<o> -F name=<n> [-F after=<cursor>]`, timeout 60 s

Two query shapes per repo. Every response includes `rateLimit { cost remaining resetAt }`.

**PROBE** (1 point; always sent first):
```graphql
query($owner:String!,$name:String!){ repository(owner:$owner,name:$name){
  issues(first:1, orderBy:{field:UPDATED_AT,direction:DESC}){ totalCount nodes{updatedAt} }
  pullRequests(first:1, orderBy:{field:UPDATED_AT,direction:DESC}){ totalCount nodes{updatedAt} }
  openPrs: pullRequests(states:OPEN, first:50){ nodes{ number mergeable reviewDecision statusCheckRollup{state} } }
} rateLimit{cost remaining resetAt} }
```
The probe's `data.repository` is JSON-serialised with sorted keys; that string is the "answer". The full query runs only if the answer differs from the one stored at the last full fetch.

**QUERY** (full, ~6 points; `_PR` fragment = `number url isDraft state mergedAt headRefName headRefOid reviewDecision mergeable statusCheckRollup{state}`):
```graphql
repository{
  issues(states:OPEN, first:100, orderBy:{field:CREATED_AT,direction:DESC}){
    pageInfo{hasNextPage endCursor}
    nodes{ number title state
      labels(first:100){nodes{name}}
      parent{number}
      subIssues(first:50){nodes{number title state}}
      blockedBy(first:100){nodes{number state}}
      closedByPullRequestsReferences(first:5, includeClosedPrs:true){nodes{ <_PR> }} } }
  closedEpics: issues(states:CLOSED, labels:["epic"], first:50, orderBy:{field:UPDATED_AT,direction:DESC}){
    nodes{ number labels(first:20){nodes{name}} subIssues(first:50){nodes{number title state}} } }
  mergedPrs: pullRequests(states:MERGED, first:50, orderBy:{field:UPDATED_AT,direction:DESC}){
    nodes{ number title url mergedAt headRefName headRefOid body
           closingIssuesReferences(first:10){nodes{number parent{number}}} } }
  openPrs: pullRequests(states:OPEN, first:50, orderBy:{field:UPDATED_AT,direction:DESC}){
    nodes{ title body <_PR>
      latestOpinionatedReviews(first:20){nodes{state author{login}}}
      checks: statusCheckRollup{contexts(first:1){totalCount}}
      reviewThreads(first:100){nodes{isResolved isOutdated}}
      closingIssuesReferences(first:10){nodes{number}} } }
}
```
**ISSUES_PAGE** (follow-up, same issue node fields): `issues(states:OPEN, first:100, after:$after, orderBy:{CREATED_AT DESC}){pageInfo{hasNextPage endCursor} nodes{...}}` with `$after:String`. Followed while `hasNextPage`, up to `MAX_ISSUE_PAGES=5` pages total (500 issues); nodes are appended and `issues_truncated = hasNextPage` of the last page. A failed page aborts the whole full fetch (data kept, marked stale).

Ceilings: 100 labels, 50 sub-issues, 100 blockers, 5 PRs/issue, 50 merged, 50 open PRs, 100 threads/open PR (undercounts beyond), 20 reviews, 50 closed epics.

### 1.2 Other GraphQL / REST / CLI calls

| Caller | Call | Notes |
|---|---|---|
| gh sign-in (`ui_gh.check`) | `gh api user --jq .login`, timeout 60 | ok = rc 0 and non-empty login. Error = first line of stderr (else stdout), `[:200]`, default `gh did not answer`. |
| branch list (`ui_gh.branches`) | `gh repo view <repo> --json defaultBranchRef -q .defaultBranchRef.name` (30 s), then `gh api repos/<repo>/branches --paginate --jq '.[].name'` (60 s) | repo must match `[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+`, no `.`/`..` segment -> else 400 `repo must be owner/name`. Returns `{branches:[default, ...sorted others], default}`; gh failure -> 502 `{error: last line [:200]}`. Never cached. |
| issue popup (`ui_issue.fetch`) | `gh api -H "Accept: application/vnd.github.html+json" repos/{o}/{r}/issues/{n}` and `.../issues/{n}/comments?per_page=100` (same header), 30 s each | 404 when stderr has `Not Found`/`HTTP 404`; else 502 (last stderr line). Output fields: number,title,url(html_url),state,state_reason,is_pr(`pull_request` key present),merged,author(login or `ghost`),created_at,labels[{name,color}],assignees[login],milestone(title),body_html(links get `target="_blank" rel="noopener noreferrer"`),comment_count(`comments`),comments[{author,created_at,body_html}]. `MAX_COMMENTS=100` (one page). Name regex `[A-Za-z0-9][A-Za-z0-9._-]*`, n digits. |
| New-run picker (`ui_issue.open_items`) | `gh issue|pr list --repo o/r --state open --limit 100 --json number,title,labels,updatedAt,url[,isDraft]` (30 s) | kind must be `issue`/`pr` else 400. Sorted by `updatedAt` desc. Item `{number,title,labels[name],updated_at,draft,url(only if https://)}`. One page, no paging. |
| PR popup (`ui_pr.fetch`) | 6 parallel calls, 40 s each: `gh api -H html repos/o/r/pulls/n`; `gh api .../pulls/n/files?per_page=100`; `.../commits?per_page=100`; `gh api -H html repos/o/r/issues/n/comments?per_page=100`; `gh api -H html .../pulls/n/reviews?per_page=100`; `gh pr view n -R o/r --json statusCheckRollup` | 404/502 as above. Patch caps: per file 60 000 chars, total 500 000 (a file over either gets `patch:null, patch_cut:true`). State: merged -> `merged`; draft && open -> `draft`; else REST state. `conflict = mergeable_state=="dirty"`. Check bucket: CheckRun done iff `status==COMPLETED`; StatusContext done iff state not PENDING/EXPECTED; red if result in {FAILURE,TIMED_OUT,CANCELLED,ACTION_REQUIRED,STARTUP_FAILURE,ERROR}, else green; not done -> pending. Conversation = comments + reviews (skip PENDING reviews and empty COMMENTED reviews) sorted by time. Commits: sha[:7], first line of message, author login else commit author name else `ghost`. |
| Issue title (`ui_board.fetch_title`) | `gh issue view n --repo o/r --json title -q .title` (30 s) | fallback text `Issue #n (title unavailable)`. |
| PR ref resolving (`parse_pr_ref`) | bare number: `gh repo view --json nameWithOwner -q .nameWithOwner` in cwd | see section 6. |
| CI (`ci.py`) | `gh pr view N --repo S --json headRefOid,mergeable`; `gh pr checks N --repo S --json name,state,bucket,link`; `gh run view <run_id> --repo S --log-failed` (300 s) | section 6. |
| Threads (`threads.py`) | GraphQL `reviewThreads` list query + `resolveReviewThread` mutation | section 6. |
| Merge cleanup | local `git` only (`worktree list --porcelain`, `status --porcelain --ignored -uall`, `rev-list`, `for-each-ref`, `cat-file -e`, `symbolic-ref`, `worktree remove --force`, `branch -D`), 60 s | section 5. |
| Repo origin | `git -C <p> remote get-url origin` (10 s), regex `github\.com(?::\d+)?[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$` (handles `ssh.github.com:443`) | section 2.1. |

No ETags / `If-None-Match` and no REST polling anywhere: conditional fetching is done by the PROBE answer comparison. No Projects v2 GraphQL is called by the engine (blubird's `set-status.sh` does that inside skills).

### 1.3 Poller state machine (`Poller`)

Per-repo in-memory entry (never persisted; a restart starts empty and stale):
`{data, stale=True, fetched_at=None, error=None, next_due=0, paused_until=0, last=0, full_at=0, probe=None}`; plus global `budget={remaining:None, reset_at:0}`.

Constants: `POLL_SECONDS=60`, `FAST_POLL_SECONDS=15` (any open PR with ci `pending`), `COLD_POLL_SECONDS=600`, `FULL_EVERY=600`, `RATE_LIMIT_PAUSE=600`, `LOW_BUDGET=1000`, `MERGED_DAYS=7`, tick 5 s, gh timeout 60 s.

- `snapshot(repo)`: from memory only, never waits: `{data, stale, fetched_at, error, retry_at}`; `retry_at = paused_until` if now < paused_until else null. Before first fetch: `data=empty()` (`issues,merged,open_prs,closed_epics` = `[]`, `issues_truncated=false`), `stale=true`, `fetched_at=null`.
- `due(repo, hot)`: `now >= max(next_due, paused_until, hot ? 0 : last + COLD_POLL_SECONDS)`.
- Loop (`start(repos, tick=5, hot)`): every 5 s, for each repo of the watched set, `poll(repo)` if `due(repo, repo in hot-set)` (hot=None => all hot).
- `poll(repo, full=false)`:
  1. If now < paused_until: return snapshot, no call. Else `last = now`.
  2. Run PROBE. On failure (below) -> stale, keep data.
  3. `full = full || answer != e.probe || now - e.full_at >= 600`. If not full: data in memory is current (`fresh=true`). Else run QUERY (+ISSUES_PAGE pages), `normalize()`; on success set `data, full_at=now, probe=answer`; on normalize error: `stale=true, error=str[:200]`.
  4. If fresh: `stale=false, fetched_at=now, error=null`; `wait = 15 if any PR (issue.prs state OPEN, or open_prs) has ci pending else 60`; `next_due = now + (max(wait,600) if low-budget else wait)`. If not fresh and not paused: `next_due = now + 60`.
  5. If fresh, call `on_fresh(repo, snapshot, prev_data)` (exceptions swallowed + logged). `prev` is the data before this poll.
- Low budget: `remaining < 1000 && now < budget.reset_at` (read from every response's `rateLimit`; `resetAt` ISO parsed to epoch). Slows every repo to >= 600 s cadence.
- `_call` error handling: rate limited if stderr contains `rate limit` (case-insens.) OR stdout JSON has `errors[].type == "RATE_LIMITED"` (payload text is never matched: issue titles may say "rate limit"). Then `stale=true, error="rate limited"`, `paused_until = budget.reset_at if (low and reset_at > now) else now + 600`; keep last data. Other failure (non-zero rc, non-JSON, or `errors` present): `stale=true, error = str(errors or stderr)[:200]`, retry on normal cadence (`next_due = now+60`). After a rate-limit pause ends, the next poll clears error/retry_at.
- Which repos are polled (`ui_server._watched_copy`): registered repos (checkouts) whose slug does not start `local/`, AND (opened by the UI in the last 7 days [`ui_watch`] OR has a live session OR dispatch lane). Hot set (`_hot`): repos requested within `VIEW_SECONDS=120` (a `?repo=` request or the global Inbox/board marks `"*"` => all watched hot) or with a live session. First view of a repo triggers an immediate async `poll`. A GitHub write (board action) calls `poll(repo, full=true)` synchronously ("repoll"); the board Refresh runs `poll(full=true)` on a thread.
- `ui_watch` persistence: `<data dir>/ui_opened.json` = `{slug: unix_seconds}`; `touch` writes at most once per 60 s per repo and prunes entries older than 7 days (`DAYS=7`); `recent()` returns slugs younger than 7 days; non-numeric values dropped on read.
- gh sign-in cache (`ui_gh.status`): `{ok, login, error}`, TTL 60 s. Cold: block on the call; stale: serve old value and refresh in a background thread (single refresher flag); a refresh whose error starts `timed out` keeps the previous value (a slow network is not a sign-out). `solo(repo)` = login set and `repo.owner.lower() == login.lower()`.

### 1.4 `normalize(response)` -> snapshot `data`

Raise `ValueError` if `data.repository` is not an object. `nodes` helper drops non-objects.

**issues[]** (open only, epics included, newest first): `{n,title,state("OPEN"),labels[names],priority,parent,sub_issues[numbers],closed_subs[{n,title}],blocked_by[{n,state}],prs[]}`.
- `priority` = text after `:` (stripped) of the first label whose lower-case starts `priority:`; empty -> null.
- `parent` = `parent.number` or null. `closed_subs` = sub-issues with state CLOSED.
- `blocked_by` includes all blockers (OPEN and CLOSED); consumers filter on OPEN.
- `prs[]` per issue from `closedByPullRequestsReferences`: `{n,url,draft,state,merged_at,head,sha,ci,review,conflict}`.

**PR field derivation (`_pr`)**: `ci` = map of `statusCheckRollup.state` upper-cased: SUCCESS->success; FAILURE,ERROR->failure; PENDING,EXPECTED->pending; anything else/missing->`none`. `review` = APPROVED->approved, CHANGES_REQUESTED->changes_requested, REVIEW_REQUIRED->review_required, else `none` (repo has no review rule). `conflict = mergeable=="CONFLICTING"` (UNKNOWN is not a conflict). `draft=isDraft`, `sha=headRefOid`, `head=headRefName`.

**Issue-reference extraction (`_refs`)** for staging-targeted PRs (GitHub only links "Closes #n" to PRs into the default branch): ordered unique union of (a) `closingIssuesReferences`, (b) regex `\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)\b` (case-insens.) over the PR body, (c) branch regex `^issue-(\d+)(?:-|$)`.

**merged[]** (PRs merged in last 7 days by `mergedAt >= now-7d`, in API order = updatedAt desc): `{n,title,url,merged_at,head,closes[_refs],epic,sha}`. `epic` = `parent.number` of `closes[0]` if GitHub linked it; else if `closes` non-empty and parent null, the `parent` of the still-open issue with that number from `issues`; else null.

**open_prs[]**: `_pr` fields minus `merged_at,state`, plus `title` and: `reviewer` = login of the LAST approving entry in `latestOpinionatedReviews`; `changes_requested = review=="changes_requested" or any review state CHANGES_REQUESTED`; `approved = !changes_requested and (review=="approved" or (review=="none" and reviewer != null))`; `checks = statusCheckRollup.contexts.totalCount or 0`; `threads_open` = count of reviewThreads with `!isResolved && !isOutdated`. Also, for each `_refs(pr)` issue that is in `issues` and has no PR with that number yet, append a copy of the PR (state OPEN) to that issue's `prs` (this is how staging-targeted PRs attach).

**Merged-into-non-default fix-up**: for each merged PR, for each `closes` issue still open and without that PR in `prs`, append `{n,url,draft:false,state:"MERGED",merged_at,head,ci:"success",review:"none"}`. (A PR merged into `staging` leaves the issue open until the skill closes it; the board must show it as Merged.)

**closed_epics[]**: `{n,labels,closed_subs}` for the 50 most-recently-updated CLOSED issues labelled `epic`.

`issues_truncated` = last-page `hasNextPage`.

---

## 2. Products, repos, docs repo, PRDs, epics, issues

### 2.1 Registries on disk

| File | Shape | Writer |
|---|---|---|
| `<data>/checkouts.json` | `{ "owner/name": "/abs/path" }` (legacy `local/<name>` keys allowed) | `register_checkout` (flock + atomic), `rename_checkout(old,new)` (refuses if `old` missing or `new` exists case-insens.), `remove_checkout`. Missing/empty/non-JSON/non-object reads as `{}`. |
| `<data>/products.json` | `{ "<docs repo slug>": "/abs/path/to/docs/checkout" }`, one row per docs repo (old-case duplicates deleted on save) | `ui_products._save` (flock, `backup_if_corrupt`, atomic) |
| `<data>/ui_opened.json` | see 1.3 | `ui_watch` |
| `<data>/issue_grind.json` | `{ "owner/repo lowercased": { "<issue>": bool } }` (non-bool/non-digit dropped) | `set_issue_grind` |
| `<data>/ui_settings.json` | per-repo `{auto_grind:bool, slack_channel:str, reviewers:[str]|null}`; legacy global `auto_grind` migrated onto every registered repo via `setdefault` | Settings form |

`repo_settings(slug)` = repo block with defaults (`auto_grind:false, slack_channel:"", reviewers:null`) plus `issue_grind` map.

### 2.2 Blubird product model as implemented (`ui_products.py`)

A product = Documentation Repo + the code repos listed in its `.blubird/repos.json` (read from disk on every call, never stored).
- `read_map(path)`: file `<path>/.blubird/repos.json`. Errors (ValueError text, surfaced as the product's `error`): `no .blubird/repos.json in {path}`; `repos.json is not valid UTF-8`; `repos.json is not valid JSON: {e}`; `repos.json must be a JSON object`; `repos.json must have a non-empty `repos` list`; `repos.json entry {i} is not an object`; `repos.json entry {i} has no string `{k}`` for `k` in `name,role,repo,path` (non-empty string, no NUL); `repos.json entry {i}: repo {r!r} is not owner/name` (regex `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`).
- Entry path resolved `realpath(join(docs_path, entry.path))`; `cloned` = `<path>/.git` exists (dir or worktree file; no git subprocess).
- `register(path)`: must be a string; `validate_repo` (absolute path, no `..` segment, realpath is a dir, `git rev-parse --show-toplevel` non-empty else `not a git repository: {path}`); docs repo needs a GitHub origin slug (`{top} has no GitHub origin`); read map; for each entry: same repo slug mapped to two different paths -> error `{repo} is mapped to both {a} and {b}`; an entry resolving to the docs repo but naming a different slug -> `{repo} points at the docs repo {slug} itself`; skip the docs repo's own `.` entry and uncloned entries; a code repo already registered at a different realpath -> `{repo} is already registered at {old}, the map points at {resolved}`; nothing is written until all validation passes. Then register docs repo as a checkout (origin must equal slug: `that folder's origin is {found or 'not a GitHub repo'}, not {slug}`), each new cloned code repo as a checkout, and save `products.json`. Idempotent (no second key in another case). Returns the product row.
- `list_products()` -> sorted by docs slug: `{docs_repo, path, repos:[{name,role,repo,path(resolved),cloned,conflict?}], error?}`. Non-string path rows skipped. `conflict` = another product's docs repo that also lists (or is) this repo slug. File reads only (runs per poll tick).
- `product_of(slug)`: first product without `error` whose docs repo or any listed repo equals `slug` (case-insens.).
- `mapped(path)`: `.blubird/repos.json` or `.blubird/docs-repo` exists; never raises.
- `sync()`: register every cloned mapped repo that is not yet a checkout; errors per repo swallowed. NOTE: documented as called by the poll loop but NOT wired into the server in this codebase (only tests call it). Setu should call it each poll tick.
- `ui_repos.docs_repo(cwd)`: cwd itself if it has `.blubird/repos.json`; else read first line of `.blubird/docs-repo` (relative path, `..` allowed), `validate_repo(realpath(join(cwd,line)))`, require its `.blubird/repos.json` else `{cwd}'s .blubird/docs-repo points at {top}, which has no .blubird/repos.json`; else `{cwd} has no .blubird map or docs-repo pointer: map it, or run /blubird:agentic-onboard`. Used so a step whose registry entry has `runs_in == "docs"` is started in the Docs repo.
- Product routes: `GET /api/products` -> list; `POST /api/products {path}` -> register (400 with ValueError text).

### 2.3 Repo registry (`ui_repos.py`)

- `list_repos()`: first `promote_local()` (every `local/<name>` checkout whose dir exists and now has a GitHub origin is renamed to `owner/repo`; no-op if that name is taken). Returns `[{slug, name, path}]` sorted by slug; `name` = worklog `projects.json` display name else slug.
- `register(slug, path)`: slug must match the slug regex ("slug must look like owner/repo"), path string, `validate_repo`, origin must equal slug case-insens., then `register_checkout(slug, top)`.
- `resolve_repo(repo)` -> `(cwd, slug|None)`: registered slug (case-insens.) -> its validated path; else treat as path, find registered slug by realpath, else origin slug.
- `find_clones(roots, slug?, max_depth=4, budget_s=4.0)`: `os.walk`; a dir containing a real `.git` directory (worktrees skipped) with a GitHub origin is a clone; do not descend into clones; skip dot dirs and `node_modules,vendor,venv,dist,build,target,Library,Applications`; stop at depth 4 and at the time budget; dedupe by dirpath. `scan_and_register(roots)` uses 20 s budget, registers unknown clones, first-found wins, others reported as `duplicates`. `default_roots()`: existing of `~/{Documents/Projects,Projects,Developer,code,work,dev,src,Documents}`.
- `is_unregistered_slug(repo)`: matches slug regex, not absolute, not registered.
- `_remember(slug,cwd)`: after a session starts with a manually typed checkout, register it.
- `start_session` guards that touch GitHub semantics (the rest is session area): `issue` positive int; `Issue URL in the prompt (github.com/o/r/issues/n)` overrides the picked repo when registered; GitHub-only commands (`create-tasks, refine-issues, implement-issue, pr-grind, pr-review, release-pr`) on a `local/*` slug fail with `{slug} has no GitHub remote yet: add one (git remote add origin …), then run {fam}` (or `…origin {taken} is already registered to another checkout: remove one, then run {fam}`); implement-issue / pr-grind with `link={owner,repo,issue}` refuse a second live session of the same family+issue -> 409 `{fam} already running for o/r#n (session {id})`; issue number is parsed from args regex `^(?:#|.*/(?:issues|pull)/)?(\d+)$` (first token).
- Inbox `repo_unpublished` setup item for every registry slug starting `local/`.

### 2.4 PRD discovery and status (`ui_planning.py`)

Current engine: a PRD is each `docs/prds/*.md` (FLAT glob, sorted by path) in the repo checkout. First 4000 chars parsed:
- status regex `\*\*Status:\*\*\s*([A-Za-z ]+?)\s*(?:·|\||$)` (multiline), mapped (lower-case) `draft->Draft, "in review"->"In review", approved->Approved, done->Done`; missing/unknown -> `Draft`.
- slug regex `\*\*Slug:\*\*\s*`?([A-Za-z0-9._-]+)`?` else file stem. Title regex `^#\s+(?:PRD\s*[—–:-]\s*)?(.+?)\s*$` (multiline) else stem.
- Label `prd-<slug>` ties epic and issues.
- epic = first OPEN issue labelled both `epic` and `prd-<slug>`.
- kids = open issues (not the epic) where (epic exists and (`parent == epic.n` or `n in epic.sub_issues`)) OR (not an epic and carries label `prd-<slug>`).
- `refined` count = kids labelled `refined`. `done_epic` = epic else a closed epic with the label; `closed_children` = its `closed_subs`.
- `pr` (only status In review): first open PR whose `head` or `title` contains the slug (heuristic) -> `{n,url}`.
- **column**: Draft->`draft`; In review->`in_review`; Done->`done`; else (Approved): kids non-empty -> `refined` if all kids refined else `tasks_filed`; elif (epic with any sub_issues) or (no epic and a closed epic has the label) -> `done`; else `approved`.
- Card: `{slug,title,status,path(relative to checkout),abs_path,column,pr,epic(n|null),issues(len kids),refined,unrefined[sorted n of kids not refined],closed_children[sorted {n,title}],children[sorted {n,title,refined}],panel}`; response `{repo, stale, fetched_at, prds}`; the server adds `account` (pinned Claude account label, session area) and `error`, `retry_at` from the snapshot.

---

## 3. Delivery board (`ui_delivery.py`) and board status mapping

`build(repo, snapshot, sessions, grind_index, settings, cleanup_flags, solo)` -> `{repo, stale, fetched_at, running, auto_grind, truncated, lanes[]}`.

- Lanes: one per OPEN epic (issue with label `epic`) plus a final `No epic` lane (`epic:null`); sorted epics ascending, No-epic last; lane title = epic title with a leading `Epic:` removed and trimmed; `running` = count of live implement-issue sessions for this repo (same on every lane).
- Epic membership of a non-epic issue: `parent` if that parent is an open epic; else via map built from each epic's `sub_issues` and each epic's `prd-*` labels (issue number in an epic's sub_issues, or issue carries the same `prd-*` label); else No epic.
- Skip: epic issues themselves; any open issue that has a PR with state MERGED (its card is in Merged).
- **Column for an open issue** (`COLUMNS = unrefined, ready, in_progress, draft_pr, in_review, grinding, merged`): the first OPEN PR (in `issue.prs`) decides: grind state exists and != `done` -> `grinding`; else draft -> `draft_pr`; else `in_review`. No open PR: live implement-issue session -> `in_progress`; else label `refined` -> `ready`; else `unrefined`. A closed-unmerged PR is ignored.
- Card: `{n,title,column,grind_on,mergeable,priority,blocked_by[open blocker numbers],pr:{n,draft,ci,url,review,conflict}|null,session:{id,status}|null,grind:{state,round,reason,thread}|null,needs_cleanup:null}`. `grind` hidden when none or state `done`; `reason` has a leading `"<ISO> — "` stamp stripped (`split_reason`, regex `^\s*(\d{4}-\d\d-\d\dT[\d:.]+(?:Z|[+-]\d\d:\d\d)?) — `).
- Merged cards (from `data.merged`, in snapshot order): `n = closes[0] or PR n`, `column:"merged"`, lane = `m.epic` if that epic is an open epic else No epic, `pr:{n,draft:false,ci:"success",url,review:"none"}`, `needs_cleanup = cleanup_flags[n]` (from section 5).
- Live session definition: status in `ui_sessions._LIVE` (starting, running, waiting, limited, queued), session command is the registry's `implement-issue` skill with an issue key (`ui_runner._issue_key`), session repo slug (from `link.owner/repo`, else registry lookup of a checkout path) equals repo (case-insens.).
- Grind index key: `(owner.lower(), name.lower(), prNumber)` -> `{state: running|idle|paused|done, round, reason, thread}`.
- `grind_on(settings, issue) = settings.issue_grind.get(issue, settings.auto_grind == true)`.

### Mapping to blubird's board statuses (for setu)

| Engine column (derived, GitHub labels + PR state + live session) | Blubird Projects v2 status |
|---|---|
| `unrefined` (no `refined` label) | Backlog |
| `ready` (`refined`, no open PR, no live session) | Ready (blubird also requires all blockers closed; engine shows blockers on the card but still lists as ready) |
| `in_progress` (live session, no PR) | In progress |
| `draft_pr`, `in_review`, `grinding` | In review (blubird moves In review only after CI green + comments handled) |
| `merged` (merged PR within 7 days) | Done |
Engine has NO notion of the Project board status; blubird's `set-status.sh` sets it, the engine never reads it.

---

## 4. Inbox, merge gate, urgency, notifications

### 4.1 Merge gate (`merge_gate.blockers(pr, solo)`)
Ordered, first hit wins: `PR is a draft` -> `PR has a merge conflict` -> `changes requested` -> `unresolved review threads` (`threads_open > 0`) -> `no approving review` (skipped when `solo`) -> None. CI mode and grind are the callers' job.

`merge_ready(pr, grind, grind_on, solo)` (Inbox + board): false if no PR or `pr.ci != "success"`; if `grind_on` and `grind.state != "done"` false; else `blockers(pr, solo) is None`. Board passes `{...issue.pr, ...open_prs[n]}` so approval/thread fields exist.

### 4.2 Inbox build (`ui_inbox.build`, pure) -> `{items, stale}`

Item: `{key, group, type, repo, at, ...fields}` + `urgency` after ranking. `key` stable across polls; `at` ISO or null. Groups in priority order `block, answer, decide, fix, setup, wait`.

| group/type | Derivation | Key | Fields |
|---|---|---|---|
| block `gh_auth` | `gh.ok == false` | `gh_auth` | error; repo=null (always shown even when filtered by repo) |
| answer `question` | session `status=="waiting"` and `pending_question.status=="pending"` | `question:{sid}` | session_id, command, link, round_id, questions, process_alive (sid in alive set); at=started_at |
| fix `session_failed` | `status=="failed"`, `panel_role != "lens"`, no `bootstrap`, not `dismissed`, and it is the NEWEST session with same (repo slug, command) (`started_at >= newest`) | `failed:{sid}` | session_id, command, link, error; at=ended_at |
| wait `limited` | `status=="limited"` | `limited:{sid}` | account (label from claude_cmd), resets_at=`limit_resets_at`, auto_resume = `auto_resume==true and not hold` |
| wait `queued` | `status=="queued"` | `queued:{sid}` | reason=`note` |
| decide `review_cap` | newest peer-review panel per artifact (ids start with timestamp), artifact path contains `docs/prds/`, `prd_status != "Approved"`, `state=="cap reached"` | `review_cap:{panel}` | prd_path (from `docs/prds/` on), panel, round, max_rounds, note `"{approved} of {total} lenses approve at round {round}"`; at parsed from `p-YYYYMMDDTHHMMSS...` |
| decide `review_approved` | same but `state=="approved"` | `review_approved:{panel}` | prd_path, panel |
| decide `prd_comment` | DROPPED (shares) | | |
| fix `grind_paused` | grind index state `paused`; if repo snapshot fresh, only when the PR is still in `open_prs` | `grind:{repo}#{pr}` | pr, issue (via snapshot issues' prs), round, reason (stamp stripped); at = stamp |
| fix `needs_cleanup` | `flags[repo][issue]` (section 5) | `cleanup:{repo}#{n}` | issue, uncommitted[], unpushed[] |
| decide `bootstrap_waiting` | bootstrap run state `waiting` | `bootstrap:{id}:audit:waiting` | run_id, issue, next_phase `decide`; at=updated_at |
| fix `bootstrap_stopped` | run state `stopped`; phase = first phase with state `failed` (else phases[0]) | `bootstrap:{id}:{phase}:stopped` | run_id, issue, phase, session_id, error |
| setup `repo_unpublished` | registry slug starts `local/` | `unpublished:{slug}` | slug, path |
| fix `pr_conflict` | fresh snapshot, open PR with `conflict` | `pr_conflict:{repo}#{n}` | pr, issue, title, url (and then no pr_ready for it) |
| decide `pr_ready` | fresh snapshot, open PR, `merge_ready(p, grind, grind_on(settings, issue), solo)` | `pr_ready:{repo}#{n}` | pr, issue, title, url, reviewer, checks |

Rules:
- Sessions with `role == "away-answerer"` are skipped. Sessions are local state: always counted.
- A repo is "fresh" if its snapshot is not stale and `fetched_at != null`. Stale/missing snapshot repos contribute no poller-derived items (`pr_ready`, `pr_conflict`, issue numbers of grind_paused, and the closed-PR check). Result `stale` = sorted list of watched repos (the `repo` param, else `watched`, else snapshot keys) that are not fresh.
- Repo spelling: names mapped case-insens. to the registered slug. `repo` filter keeps items whose repo is null or equals it (case-insens.).
- Dispatch lanes (herdr dispatch) and `prd_comment` shares: DROPPED.
- **Sorting (`rank`)**: sort by (group order, `-urgency` (None=0), `-time(at)` (None=0)). Build first ranks with urgency None (pure time order); the server re-ranks with cached urgency.
- Dismissal state: the only dismissal is session `dismissed` (hides `session_failed`); there is no generic dismissed-items file. Items disappear when their cause does (derived, never stored). "What needs you" = everything in the table; `block` first.
- Notifications on a fresh poll (`ui_server._on_fresh`; skipped when snapshot stale): if `prev != empty()` ("first" poll sends nothing): (a) for each PR draft in `prev` and ready now (`ui_grind.turned_ready`: open PR not draft now and draft before; a PR first seen ready does not count) push `pr-ready` id `{repo}#{n}:ready`; (b) newly merged PR numbers (not in prev.merged) -> run merge cleanup for their `closes` issues (heads map issue -> merged `sha`), notify `needs-cleanup` id `{repo}#{n}:cleanup` once per flagged issue and store flags in `_flags[repo][issue]` (in-memory only; lost on restart, recomputed only for newly merged PRs); (c) grind autostart: for each turned-ready PR whose issue's `grind_on` is true, no grind state file, no live grind, start `/pr-grind <pr url>`.

### 4.3 Urgency (`ui_urgency.py`) - optional LLM scoring via the `jev` CLI
- Scorable types: `question, grind_paused, session_failed, pr_conflict`. Text: question = joined question text, grind_paused = reason, session_failed = error, pr_conflict = constant `A pull request has a merge conflict with its base branch.`; empty -> unscored.
- Question `How urgent is this item for the person running these coding sessions?`, levels (low->high): `cosmetic, can wait` / `minor, can be handled later today` / `work is waiting on it, but nothing is lost by waiting` / `blocking work in progress or about to affect other people` / `irreversible, outward-facing or blocking work right now`.
- Urgency = `clamp(int(score + 0.5) + 1, 1, 5)` (round half up). `urgency(item)` only reads jev's cache (never blocks).
- Scanner timer every 30 s: skip if jev not `ok` or `spent() >= 400` calls/hour; pick up to `PASS_MAX=3` uncached, not in-flight, distinct texts; score on a pool of 3 workers. If setu drops jev, urgency is always null and ranking is group then newest-first.

---

## 5. Merge cleanup, worktrees, sessions (`ui_mergeclean.py`, `ui_cleanup.py`)

Engine model: implement-issue works in `<checkout>/.worktrees/<n>-<slug>` on branch `issue-<n>-<slug>` (blubird's worktree location may differ; setu must resolve it from `git worktree list --porcelain` filtered to `<checkout>/.worktrees/`, as below).

- `_worktrees(checkout)`: parse `git worktree list --porcelain`; keep entries whose realpath starts with `realpath(<checkout>/.worktrees)/`; record `branch` from `branch refs/heads/<b>`.
- `_plan(checkout, n)`: worktree = first whose basename starts `{n}-` or branch starts `issue-{n}-`; branch = that worktree's branch, else first of `git for-each-ref --format=%(refname:short) refs/heads/issue-{n}-*`.
- `check(checkout, n, merged_head)` -> None (loses nothing) or `{uncommitted:[paths], unpushed:[shas]}`:
  - uncommitted = lines of `git -C <wt> status --porcelain --ignored -uall -- . <excludes>` (path = `line[3:]` stripped and unquoted); excludes `:(exclude,glob)**/{d}/**` for regenerable dirs `__pycache__, build, dist, node_modules, target, venv, .venv, .next` (sorted). Ignored files like `.env.local` count as uncommitted.
  - unpushed = `git rev-list <branch> --not [<merged_head>] --remotes`, with `<merged_head>` excluded only if `git cat-file -e <sha>^{commit}` succeeds (a squash merge deletes the remote branch; the PR's head sha counts as pushed).
  - Missing worktree = clean; only the branch is considered.
- `clean(checkout, n, confirm=false, merged_head)` -> `{removed:[...], flagged}`: if flagged and not confirm -> `{removed:[], flagged}`. Else remove the worktree (`git worktree remove --force`, only if it exists and its path is under `.worktrees/`; failure only warns), then delete branch with `git branch -D` only if it fully matches `issue-{n}-.+` and is not the main checkout's current HEAD (`symbolic-ref --short -q HEAD`). Remote branches are never touched.
- `on_merged(repo, issues, checkout?, heads?)`: resolve checkout (registry; unknown -> `{}`; must be a dir), `clean(confirm=false)` per issue (exceptions logged and skipped), return `{issue: flags}` only for flagged ones. Cards then carry `needs_cleanup`.
- Manual cleanup `POST /api/cleanup {repo, issue:int>=1, confirm:true}`: 400 unless valid; requires the issue (or PR number) in the repo snapshot `merged` list else 409 `#{n}'s PR is not merged`; runs `clean(confirm=true, merged_head=pr.sha)`; clears the flag; returns `{removed}`.
- Session cleanup (`ui_cleanup`): `LIVE = starting, running, waiting, limited, queued`. `find_targets()` = finished sessions `{key:id,label:command||"session",repo,flags:[]}` newest first. `clean(keys)`: only keys that are still finished targets (re-derived; client never names paths), reload, skip if now live or gone, `rmtree(<sessions dir>/<id>)` (never a checkout, worktree or branch). `GET /api/sessions/cleanup`, `POST /api/sessions/cleanup`.
- Blubird's own after-merge (inside the implement-issue skill, not the engine): confirm base holds the content, close issue + Done, stop dev stack, remove worktree + local AND remote branch, update main checkout, move unblocked issues to Ready. Engine does only the local worktree/branch part above.

---

## 6. CLI used by skills

### 6.1 `aiw ci status <pr> [--watch] [--timeout 1200]`
`<pr>`: URL `github.com/o/r/pull/N`, `owner/repo#N` (also `owner/repo N`), or bare `N` (owner/repo from `gh repo view --json nameWithOwner -q .nameWithOwner` in cwd; failure -> exit USAGE with `cannot resolve owner/repo for PR N: ...`; unrecognised -> `unrecognised PR reference: ... (want a URL, owner/repo#N, or N)`).
`snapshot(owner,repo,N)`:
1. `gh pr view N --repo o/r --json headRefOid,mergeable`.
2. If `mergeable == "CONFLICTING"` -> `{state:"conflict", head_sha, failing:[], note:"merge conflict with the base branch"}` (GitHub runs no CI on a conflicting PR; "no checks" must not read as green). UNKNOWN falls through.
3. `gh pr checks N --repo o/r --json name,state,bucket,link`. If gh returned non-zero, still try to parse stdout as a JSON list (gh exits non-zero for red/pending but writes JSON). If not a list: text = stderr+stdout; contains `no checks` (case-insens.) -> `{state:"green", note:"no checks configured"}`; else `{state:"error", note:text[:300]}` (rate limit/auth/timeout never read as green).
4. `state_of(rows)`: any bucket `pending` -> `pending`; else any `fail` -> `red`; else `green` (empty/pass/skipping = green). Buckets are compared lower-cased.
5. Result `{state, head_sha, failing:[rows with bucket fail]}`.
`--watch`: re-snapshot every `POLL_SECONDS=30` while state in {pending, error} and before deadline (`now+timeout`); on cap expiry with state pending/error, `note = "wall-clock cap of {timeout}s expired with checks still {state}"`. Finally each failing check is expanded to `{name, run_id, link, log_excerpt}`: `run_id` = text between `/runs/` and next `/` of `link` (else ""), `log_excerpt` = last 4000 chars of `gh run view <id> --repo o/r --log-failed` (stdout else stderr), 300 s timeout. Output: pretty JSON (indent 2) on stdout. Flake-vs-real classification is intentionally not done.

### 6.2 `aiw threads list <pr> [--open-only] [--for-comment <REST id>]`, `aiw threads resolve <node_id>...`
List query (paged by `$cursor`, 100 per page, until `hasNextPage` false):
```graphql
query($owner:String!,$repo:String!,$number:Int!,$cursor:String){ repository(owner:$owner,name:$repo){ pullRequest(number:$number){
  reviewThreads(first:100, after:$cursor){ pageInfo{hasNextPage endCursor}
    nodes{ id isResolved isOutdated path line comments(first:1){nodes{databaseId url body}} } } } } }
```
invoked `gh api graphql -f query=... -f owner=.. -f repo=.. -F number=N [-f cursor=..]`. A failed call exits 1 with `could not read review threads: <stderr or stdout[:300]>`. Output JSON array (indent 2) of `{node_id, is_resolved, is_outdated, comment_id (REST databaseId of FIRST comment), url (of first comment), path, line}`. `--open-only` keeps `!is_resolved` (outdated threads still listed). `--for-comment N`: keeps only the thread whose `comment_id == int(N)` (or `[]`); applied after open-only; `thread_for_comment` accepts int or numeric string, None/garbage -> no match.
Resolve: `mutation($id:ID!){ resolveReviewThread(input:{threadId:$id}){ thread{id isResolved} } }` via `gh api graphql -f query=... -f id=<id>`; success iff no `errors` and `thread.isResolved` true; prints `resolved <id>`. Per-thread non-fatal: failure -> warn `could not resolve {id}: {err[:200]}`; exit code 1 only if EVERY id failed (and at least one given).

---

## 7. Bootstrap / onboarding (`ui_bootstrap.py`)

Chain of one headless session per phase, started from the UI ("Bootstrap repo"), command `/repo-bootstrap <phase> [<issue>]` (engine skill; blubird equivalent is `/blubird:agentic-onboard`, a single interactive skill with no phase chain).
- Phases `PHASES = audit, decide, constitution, guides, gates, docs`. Run states `running | waiting | stopped | done | ended`; open = running, waiting, stopped. Phase states `pending | running | done | failed`.
- File `<data>/bootstraps/<12-hex id>.json` (`id = token_hex(6)`; bad id -> ValueError `bad bootstrap id`): `{id, repo, issue, branch ("bootstrap/<issue>"), phases:[{name, session_id, state}], state, error, created_at, updated_at}`; `save` sets `updated_at` (UTC ISO) and writes `indent=1` atomically. Locks: `.store.lock` (store-wide, one-run-per-repo check + save) and `<id>.lock` (per run) via flock.
- Start input (`parse_input`): `""`/`audit` -> (audit, None); `<phase> <issue>` or `<phase> #<issue>` with phase in decide..docs -> (phase, issue); else error `bad bootstrap input '...'; accepted: (empty), audit, or <phase> <issue> with phase one of decide, constitution, guides, gates, docs and issue 123 or #123`. Needs a registered GitHub repo, not `local/`.
- `create(repo, phase, issue)`: raises `Conflict` (HTTP 409) if the repo (case-insens.) has a run in an open state: `a bootstrap run is already {state} for {repo} at {phase} (run {id})`. Earlier phases are `done`, the start phase `running`, rest `pending`; run `running`.
- Tick every 5 s over `running` runs (one run's exception never stops others; global lock). For the current phase (first not done): no session id -> if `updated_at` older than 60 s (`ATTACH_GRACE_SECONDS`) stop with `phase session is gone`, else wait. Session record gone -> stopped `phase session is gone`. Session live -> wait. Session ended: success only if status `done` AND the final message's last non-blank line fully matches `BOOTSTRAP: (\w+) done #(\d+)` with the expected phase and (if run.issue set) the same issue; else stopped with `rec.error` or `phase session was stopped` / `phase ended without reporting done`. On success: phase `done`; audit also records the issue (`branch = bootstrap/<issue>`) and sets run `waiting` (user must Continue); last phase (docs) -> run `done`; otherwise next phase `running` and its session starts (same account/model/effort as the previous session, questions gated to the Inbox); a start failure -> stopped `could not start {phase}: {e}`.
- Actions (each takes the run lock, needs the right state else `Conflict`): `continue` (waiting -> running, starts `decide`), `retry` (stopped -> running, new session for the failed phase; failed start restores prior state), `stop` (running/waiting/stopped -> ended; live phase session stopped after unlocking). `discard` deletes a run whose first session never started.
- Inbox: `waiting` -> `bootstrap_waiting`; `stopped` -> `bootstrap_stopped`. Routes `GET /api/bootstraps`, POST continue/retry/stop.

---

## 8. Planning entry points: route and duplicate (`jev`-based, optional)

- `POST /api/route {text}` -> `{route: "feature"|"small_change"|null, confidence, why}`. Text required (ValueError otherwise). Question `Is this request a new feature that needs a product spec, or a small change that fits in one issue?`; options `feature` / `small_change` / `unclear`. `MIN_CONFIDENCE=0.4`; below it, or `unclear`, -> route null, why `too vague to tell`. jev non-ok statuses map to `jev is off`, `jev is not installed`, `jev did not answer`, `jev failed (exit N)`, `jev gave an unreadable answer`. whys: feature `it adds a new capability with its own decisions to settle`; small_change `it reads as a fix or one contained change`. Blubird equivalent: create-prd for behaviour change vs create-tasks for no decision.
- `POST /api/duplicate {repo, text}` -> `{match:{kind:"issue",n,title,url}|{kind:"prd",path,title,url:"#/features/<slug>?repo=<repo>"}|null, confidence, why}`. Rules: text trimmed `< MIN_CHARS=20` -> `too short to check`; jev not ok -> reason; snapshot stale or never fetched -> `issues not loaded yet`; options = up to `MAX_ISSUES=100` open issues from the snapshot (key `issue-<n>`, title[:120]) + PRDs sorted by file mtime desc (key `prd-<idx>`) limited so total options `<= MAX_OPTIONS=254` incl. `none`; no options -> `nothing to compare with`; question `Which existing open issue or PRD already asks for the same change as this request?`; `none` option text `None of these: no listed issue or PRD covers this request`. Match requires pick != none and `p >= MIN_CONFIDENCE=0.6`; unknown key -> `jev gave an unreadable answer`; non-match -> `no likely duplicate`; match why `looks like the same request`. Title/url always from own records, never from jev. Extra non-ok status `capped` -> `jev's hourly limit is reached`.

---

## 9. Account pinning (`ui_origin.py`, session-adjacent)
Sessions started with `pin_account` make PRDs/issues; later sessions on that PRD, its epic/issues or their PRs run on the same Claude account. Parsed from the pinned session's `stream.jsonl`: Write tool_use `file_path` matching `docs/prds/([\w.-]+)\.md` (PRD stems) and `tool_result` of a `gh issue create` Bash tool_use (`/issues/(\d+)` URLs) = issue numbers made. A new start matches if its text names the PRD, or its issue set (link issue, args regex `/\S+\s+((?:#?\d+[\s,]+)*#?\d+)(?=\s|$)`, issues of PRs in the text/snapshot, merged PR `closes`) intersects the issues made or the made PRD's family (epic + open and closed children from the planning card). Pinned list cached 5 s. Codex stream parsing there is DROPPED. Optional for setu.

---

## 10. Constants and pinned edge cases (checklist)

| Constant | Value |
|---|---|
| poll normal / fast (CI pending) / cold / full-every / rate-limit pause | 60 / 15 / 600 / 600 / 600 s |
| low GraphQL budget | `< 1000` remaining before `resetAt` |
| merged window | 7 days |
| issue pages / page size | 5 / 100 |
| watch recency / view window / opened-write throttle | 7 days / 120 s / 60 s |
| gh status TTL / timeouts | 60 s / 60 s (user), 30 s (branches default), 60 s (branch list) |
| bootstrap tick / attach grace | 5 s / 60 s |
| ci watch poll / default timeout / log excerpt | 30 s / 1200 s / last 4000 chars, run view timeout 300 s |
| urgency tick / pass max / hourly skip | 30 s / 3 / 400 |
| popup caps | comments/files/commits/reviews 100; patch 60 000 per file, 500 000 total |

Pinned by tests:
- Probe skips the full query when nothing changed; full runs on first poll, `full=true`, changed answer, or `FULL_EVERY` elapsed.
- Pending CI -> 15 s cadence; cold repo (`hot=false`) only due every 600 s; low budget forces 600 s cadence even with pending CI.
- Rate limit: data kept, `stale=true`, `error="rate limited"`, no calls while paused, `retry_at = reset` (low budget) or `now+600` (secondary limit); recovery clears both. Other failure: stale, `error` = message, `retry_at=null`.
- A raising poll pass does not kill the loop; `on_fresh` exceptions are swallowed.
- Truncation: 5 pages -> 4 follow-up calls, `issues_truncated=true`; a failing page => whole fetch stale with old data kept.
- Draft PR with branch `issue-7-thing` and a body `Closes #6` attach to issues 7 and 6 although GitHub linked nothing; merged-to-staging PR marks its open issue MERGED; `epic` of a merged PR comes from the open issue's parent.
- `threads_open` ignores resolved and outdated; one CHANGES_REQUESTED review defeats an approval from another reviewer; `approved` also true for `review=="none"` with an approver.
- Conflict only when `mergeable == "CONFLICTING"`.
- CI: pending beats red beats green; empty rows green; nonzero exit with JSON is read; `no checks` -> green; any other gh failure -> `error`; conflicting PR -> `conflict`; UNKNOWN mergeable -> checks; `--watch` keeps polling through `error`.
- Threads matched by first comment REST id (string or int).
- Products: invalid map shapes each reject; register twice idempotent; symlinked entry path resolved; deleted clone lists `cloned:false`; code repo registered elsewhere refused with nothing written; case-variant rows replaced; two products listing the same repo set `conflict`.
- Mergeclean: missing worktree is clean; flagged work only removed with `confirm`; never removes outside `.worktrees/`, never the checked-out branch, never remotes.

---

## 11. DROPPED features (one line each; do not port)
- Shares (`prd_comment` inbox item, `ui_shares`, share runtime/tailnet, `_share_rows`).
- Codex harness (`_codex_made`, `harness_codex`), herdr/dispatch lanes (`ui_dispatch`, `dispatch_run`, inbox lane merge, `drop_owned`), personal plugin/worklog/vault (`ui_vault`, `no_repo` runs, `projects.json` display names).

---

## 12. Engine vs blubird model: differences setu must resolve

| Topic | Current engine | Blubird (target for setu) |
|---|---|---|
| Unit of work | Single repo checkout (`checkouts.json`); `products.json` exists but board/planning/delivery are per repo | Product = Docs repo + code repos from `.blubird/repos.json` (`name, role, repo, path`); board and issues span all mapped repos; epics live in the Docs repo, child issues in the code repos |
| Docs-repo link | Read only for `runs_in == "docs"` steps and product registration; poller/planning ignore it | Every code repo has `.blubird/docs-repo` (one relative-path line); PRDs/epics always read from the Docs repo |
| PRD location/status | Flat `docs/prds/*.md`; status from a `**Status:**` header line (Draft/In review/Approved/Done), slug from `**Slug:**` | `docs/prds/<module>/<feature>.md` (nested); module is a grouping level; slug in PRD, status via PRD PR (Approved when merged) |
| Epic/issue link | Epic = open issue labelled `epic` + `prd-<slug>`; children via `parent`/`sub_issues` or `prd-<slug>` label; poller only reads ONE repo's issues | Same labels, plus children in OTHER repos (cross-repo sub-issues/blocked-by by URL); Go poller must query each mapped repo and join by epic number/URL |
| Board statuses | Derived columns (unrefined/ready/in_progress/draft_pr/in_review/grinding/merged) from labels + PRs + live sessions; no Projects v2 | Real Projects v2 field: Backlog, Ready (refined + all blockers closed), In progress, In review, Done; needs GraphQL `projectItems` read (engine never queries it) |
| Ready test | `refined` label only; blockers shown on card | `refined` AND open, all blockers closed; refine-issues / implement-issue promote |
| Base branch | PR linking handled for non-default targets (body keyword, `issue-<n>-` branch) | Always `staging`; issue not auto-closed by merge, so the skill closes it and sets Done; engine's MERGED-PR fix-up already models this |
| Branch/worktree | `issue-<n>-<slug>`, worktree `<checkout>/.worktrees/<n>-<slug>` | Branch `issue-<n>-<slug>` from `staging`; worktree path set by the skill; engine cleanup scans `.worktrees/` only |
| Merge | `merge_gate` + `Merge` button in UI, grind loop (`pr-grind`) | Humans only; agents never merge; `merge-when-green.sh` pins to a reviewed SHA and base |
| Onboarding | 6-phase `repo-bootstrap` chain with `BOOTSTRAP:` sentinel | `/blubird:agentic-onboard` (Docs repo first, writes repos.json), `--dev`, `map-prds`, no phase chain |
| Epic state | Epic stays open until closed; Done column = closed epic or all subs closed | Epic moved to In progress by refine-issues; closed when all done |
| Gaps in engine | `ui_products.sync` unwired; `_flags` cleanup state is memory-only; issues query capped at 500; reviewThreads capped at 100; no Projects v2; no cross-repo blocker resolution | Required by blubird flow |
