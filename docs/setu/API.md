# setu — API and package contract

Contract for parallel implementation. `ARCHITECTURE.md` decisions are fixed. The engine specs
(`engine/sessions.md`, `engine/github.md`, `engine/workflows.md`, cited as **S§**, **G§**, **W§**) are
the behaviour contract wherever this file says "as S§x" or says nothing. This file wins when they conflict.

Contents: 0 decisions made here · 1 module and packages · 2 Go interfaces · 3 HTTP conventions ·
4 Types · 5 endpoints · 6 SSE · 7 on-disk layout · 8 CLI · 9 prompt registry · 10 build phases and tests.

---

## 0. Decisions made in this file (beyond ARCHITECTURE.md)

| # | Decision | Why |
|---|---|---|
| D1 | One start endpoint `POST /api/sessions` replaces `/api/sessions` + `/api/start`. Card guards apply when `guard:true`. | smaller API |
| D2 | Inbox items and River cards carry server-built `actions: Action[]`. The UI runs them as given and has no per-type action logic. | UI and backend can be built in parallel |
| D3 | Added packages: `errs`, `execx`, `events`, `cli`, `views` (River/Ops/Me), `dispatch/store` (leaf, breaks the grind↔dispatch cycle), `testutil/fakebin`. | DAG, see §1.2 |
| D4 | No `--agent` (there is no plugin). peer-reviewer and away-answerer bodies are embedded in `prompts/agents/*.md` and passed through `--append-system-prompt`. Each spawn passes **one** `--append-system-prompt` = `join("\n\n", agentBody?, HEADLESS?, instructions...)`. | no plugin agents |
| D5 | Child env: `SETU_HOME`, `SETU_SESSION` (plus `AIW_UI_SESSION`, same value), `SETU_HEADLESS=1` (plus `AIW_HEADLESS=1`) for re-entries, `BLUBIRD_IDLE_GUARD=off`, `PATH=<dir of setu binary>:$PATH`. **`CLAUDE_PLUGIN_DATA` is not set** (it would hijack blubird's own plugin data). | |
| D6 | The server sends session notifications (`waiting`, `done`, `failed`). `setu ask` only writes `meta.json`. The server watches `meta.json` mtime of live sessions. | one sender, one dedupe |
| D7 | Notification channels: `browser` (SSE `toast`), `ntfy` (phone push; **kept — the owner uses it today**, exact behaviour of engine/workflows.md §notify incl. env overrides, 0600 rule, UA header, Bearer/Basic auth, 5 s timeout), `mac`, and `push` (Web Push/VAPID to the PWA) as an additional optional channel. A migrated `ui.json` keeps `ntfy`, `channels` and `public_url` unchanged; matrix default for `ntfy` = true, for `push` = false. | owner override |
| D8 | Dropped endpoints/features not in the prototype: `/api/route`, `/api/duplicate`, `POST /api/prd` (PRD edit; back as `PUT /api/prd` for the feature page), `/api/restart`, `/api/notifications` (now SSE), `/api/repos/create`, `/api/repos/publish`, `/api/github/owners` (all three back for the Create repo and Publish dialogs), bootstrap chain (`repo-bootstrap`; Ops runs `blubird:agentic-onboard`), `ui_opened.json` watch list, urgency for `prd_comment`. | smaller API |
| D9 | Watched repos for the poller = every repo of every product ∪ repos with a live session or dispatch lane. Hot = viewed within 120 s (`?product=`/`?repo=` request) or has a live session. | replaces `ui_opened.json` |
| D10 | Built-in `release-pr` ends with the line `SETU-RELEASE: {"pr":"<url>","thread":"<url>"\|null}`. `release-note` has a draft mode that writes the note file and never posts. **setu posts the note itself, exactly once**, with `slackcli messages send`. | a deterministic release flow and exactly-once posting |
| D11 | Session API field `status` (was `outcome`). New record fields `step`, `args`, `agent` (name), `kind`. Legacy records: `step` is inferred from `command` via `parse()` (S§5.3). | grind identified by metadata (W§13.3) |
| D12 | The grind CLI is the merged design (W§13.2): `setu grind …` with B's exit codes. The old verbs `grind-mode`, `grind-reviewers`, `ci status`, `threads` remain as aliases. | |
| D13 | Data dir files keep their old names and schemas where migrated (`ui_settings.json`, `checkouts.json`, …), so the copied dir is read as is. The settings API uses the on-disk key names. | migration is a plain copy |
| D14 | All errors are JSON `{error}` (no `text/plain` 404s) except the 403 from the Host guard. | |

---

## 1. Module and packages

- Module `github.com/masnun-siam/setu`, `go 1.27`. The std lib only. Allowed deps: one Web Push lib (VAPID + aes128gcm), e.g. `github.com/SherClockHolmes/webpush-go`. Nothing else without review.
- Build: `make web` (Vite → `internal/web/dist/`, committed) · `go build ./cmd/setu` · `go test ./...` · `make install`.

### 1.1 Packages and ownership

| Package | Owns | Exposes |
|---|---|---|
| `cmd/setu` | wiring only: builds services, collects `Routes`/`Commands`, starts loops | — |
| `internal/errs` | error kinds → HTTP status | `Invalid`, `NotFound`, `Conflict`, `Upstream`, `Forbidden` |
| `internal/execx` | subprocess runner (never errors; 127 missing, 124 timeout) | `Run` |
| `internal/home` | `~/.setu`, migration, atomic JSON, flock | `Home`, `ReadJSON`, `WriteJSON`, `UpdateJSON`, `Lock`, `TryLock` |
| `internal/events` | in-process pub/sub for SSE | `Bus` |
| `internal/cli` | CLI command type + dispatcher | `Command`, `Env`, `Main` |
| `internal/server` | `net/http` mux, Host guard, JSON helpers, SSE handler, static/SPA, tailscale serve | `Route`, `New`, `Handle`, `Decode` |
| `internal/web` | `embed.FS` of `dist/` | `FS` |
| `internal/settings` | `ui_settings.json`, `issue_grind.json`, `ui.json` (matrix + public_url) | `Store` |
| `internal/claude` | account argv, preflight, stream-json parse, usage meters, transcript copy | `Argv`, `ParseLine`, `Usage` |
| `internal/blubird` | detect/version/install/update | `Manager`, `Status` |
| `internal/prompts` | embedded prompts + agents, extraction, step registry, HEADLESS/REENTRY texts | `Registry` |
| `internal/gh` | `gh` wrapper, auth status, CI snapshot, review threads, popups, PR/issue writes | `Client`, `CISnapshot`, `Threads*` |
| `internal/products` | `checkouts.json`, `products.json`, `.blubird` maps, docs-repo resolution, PRD discovery, merge cleanup | `Registry` |
| `internal/poller` | per-repo GraphQL polling, snapshots, merge gate | `Poller`, `Snapshot`, `MergeBlockers` |
| `internal/notify` | notification compose + channels, `push.json` | `Service` |
| `internal/jev` | jev CLI wrapper, cache, ceiling, route classifier | `Client`, `Routes` |
| `internal/sessions` | `sessions/<id>/`, runner, follower, questions, limits, `setu ask` | `Manager` |
| `internal/grind` | `pr-grind/*.md`, `grind_notified.json`, `channels.json` (read), re-entry tick, autostart, `setu grind …` | `Service` |
| `internal/review` | `peer-review/` panels, `config.json` lenses | `Service` |
| `internal/dispatch/store` | `dispatches/*.json` types, load/list/lock, lane ownership (leaf: imports `home` only) | `Load`, `List`, `ActiveLane` |
| `internal/dispatch` | dispatch tick/step, CLI, coordinator reading | `Service` |
| `internal/away` | `afk.json`, away answerer, retries | `Service` |
| `internal/vault` | vault folders, suggest, PRD info | `Service` |
| `internal/release` | `releases/*.json`, release flow tick, note posting | `Service` |
| `internal/inbox` | derived inbox (pure build + rank) | `Builder` |
| `internal/views` | River, Ops, Me aggregates | `Service` |
| `internal/testutil/fakebin` | fake `claude`, `gh`, `slackcli`, `jev`, `git`-passthrough harness | `Install` |
| `prompts/` | `release-pr`, `pr-grind`, `release-note`, `peer-review` (`SKILL.md` + `scripts/`), `agents/{peer-reviewer,away-answerer}.md` | embedded by `internal/prompts` |
| `web/` | Preact app | built to `internal/web/dist/` |

### 1.2 Import DAG (a package imports only from lower layers)

```
L0 errs execx home events cli web
L1 server(errs,events,web) settings(home,events,errs) gh(execx,errs) dispatch/store(home)
L2 jev(execx,home,server,errs) products(home,gh,execx,events,errs) claude(execx,settings,home) blubird(execx,home,events) notify(settings,home,events,execx)
L3 prompts(home,blubird) poller(gh,events,errs)
L4 sessions(home,settings,claude,prompts,notify,events,execx,errs)        // repo lookup via interface (products satisfies it)
L5 grind(home,gh,sessions,settings,jev,poller,notify,products,dispatch/store) review(home,sessions,notify,prompts) vault(home,settings,claude,execx)
L6 dispatch(home,gh,sessions,poller,grind,settings,jev,notify,products,prompts,dispatch/store)
L7 release(home,sessions,gh,grind,settings,poller,products,notify,prompts) away(sessions,jev,dispatch,notify,prompts,settings)
L8 inbox(...all above) views(...all above)
L9 cmd/setu
```
Every package with routes imports `server` only for `server.Route` and the helpers, and `cli` for `cli.Command`.

### 1.3 Registration (`cmd/setu/main.go` is the only shared file)

Each package with HTTP routes exports `func Routes(d Deps) []server.Route`, where `Deps` is that package's own struct (§2). Each package with verbs exports `func Commands() []cli.Command`. Long-running loops: `func (s *Service) Start(ctx context.Context)` returns at once and runs supervised goroutines (a panic in a tick is logged, never fatal).

Startup order in `serve`: `home.Open` → `home.Migrate` → settings → prompts.Load (extract) → blubird.Detect → products → poller → notify → sessions.Reconcile → grind, review, dispatch, release, away → server.Listen → tailscale up → all `Start(ctx)`. SIGTERM/SIGHUP: cancel ctx, close the listener, `tailscale serve … off`. Child `claude` processes are never killed on exit.

---

## 2. Go interfaces (exact signatures)

```go
// ---- errs ----
type Kind int
const (KInvalid Kind = iota+1; KNotFound; KConflict; KUpstream; KForbidden)
type Error struct { Kind Kind; Msg string; Extra map[string]any } // Extra is merged into the JSON body (e.g. id, href)
func (e *Error) Error() string
func Invalid(format string, a ...any) error   // 400
func NotFound(format string, a ...any) error  // 404
func Conflict(msg string, extra map[string]any) error // 409
func Upstream(format string, a ...any) error  // 502
func Forbidden(format string, a ...any) error // 403
func KindOf(err error) Kind                    // 0 = unknown → 500 "internal error"

// ---- execx ----
type Opts struct { Dir string; Env []string /*appended to os.Environ*/; Stdin io.Reader; Timeout time.Duration; ExtraFiles []*os.File; Detach bool /*Setsid*/ }
type Result struct { Code int; Stdout, Stderr []byte; Err error }
func Run(ctx context.Context, argv []string, o Opts) Result // missing binary → Code 127, Stderr=err; timeout → 124 "timed out after Ns"
func (r Result) LastLine() string                           // last non-blank line of stderr else stdout, ≤200 chars

// ---- home ----
type Home struct { Root string }
func Open() (*Home, error)                         // $SETU_HOME or ~/.setu, mkdir 0700
func (h *Home) Path(rel ...string) string
func OldDataDir() string                           // $CLAUDE_PLUGIN_DATA or ~/.claude/plugins/data/ai-workflow
func Migrate(h *Home, old string) (copied bool, err error) // once; marker .migrated; copy, never delete
func AtomicWrite(path string, data []byte, perm fs.FileMode) error // tmp+fsync+rename
func ReadJSON(path string, v any) error            // missing/empty/corrupt → v untouched, returns nil; I/O error → err
func WriteJSON(path string, v any) error           // indent 2, trailing \n, atomic, 0600 for ui.json/push.json, else 0644
func UpdateJSON[T any](path string, fn func(*T) error) (T, error) // Lock + BackupIfCorrupt + read + fn + WriteJSON
func Lock(path string) (unlock func(), err error)  // blocking flock(LOCK_EX) on <path>.lock
func TryLock(path string) (*os.File, bool, error)  // non-blocking; caller keeps *os.File open to hold it
func BackupIfCorrupt(path string) (string, error)  // renames to <path>.corrupt-<unix>

// ---- events ----
type Topic string
const (TSessions Topic = "sessions"; TInbox = "inbox"; TProducts = "products"; TDispatch = "dispatch"; TUsage = "usage"; TToast = "toast")
type Event struct { ID uint64; Topic Topic; Data any }
type Bus struct{ /* … */ }
func New() *Bus
func (b *Bus) Publish(t Topic, data any)           // never blocks; slow subscriber drops events, gets a "resync" hello
func (b *Bus) Subscribe(buf int) (<-chan Event, func())
func (b *Bus) Subscribers() int                     // >0 = a UI is present (usage polling)

// ---- cli ----
type Env struct { Stdin io.Reader; Stdout, Stderr io.Writer; Getenv func(string) string; Home *home.Home }
type Command struct { Name string; Aliases []string; Summary string; Run func(ctx context.Context, env Env, args []string) int }
func Main(cmds []Command, args []string) int        // unknown verb → usage on stderr, exit 64

// ---- server ----
type Route struct { Pattern string; Handler http.Handler } // Go 1.22 mux pattern: "POST /api/sessions/{id}/answer"
type Config struct { Port int; AllowHosts []string; Tailscale bool; TailscaleHTTPSPort int; Version string }
func New(cfg Config, bus *events.Bus, routes []Route) *Server
func (s *Server) Listen(ctx context.Context) error  // probe 127.0.0.1:port first (S§7); tailscale up
type HandlerFunc func(r *http.Request) (status int, body any, err error)
func Handle(f HandlerFunc) http.Handler              // err → errs.KindOf → status + {"error":msg, ...Extra}
func Decode(r *http.Request, v any) error            // §3 body rules; returns *errs.Error with 400/413/415
func PathInt(r *http.Request, name string) (int, error)
func Slug(r *http.Request) (string, error)           // {owner}/{name} path values, validated

// ---- settings ----
type Store struct{ /* … */ }
func Open(h *home.Home, bus *events.Bus) *Store
func (s *Store) Get() Settings                        // normalized + defaults; re-read on mtime change
func (s *Store) View() SettingsView                   // GET shape (§4 Settings)
func (s *Store) Save(patch json.RawMessage) (SettingsView, error) // partial merge, S§4.1 rules; publishes usage{kind:"settings"}
func (s *Store) Accounts() []Account                  // built-in first
func (s *Store) Account(label string) (Account, bool)
func (s *Store) Default() Account
func (s *Store) CheckRun(model, effort string) error  // S§4.2
func (s *Store) IssueGrind(slug string, issue int) (on, set bool)
func (s *Store) SetIssueGrind(slug string, issue int, on bool) error
func (s *Store) Notify() NotifyConfig                 // ui.json channels matrix + public_url
func (s *Store) SaveNotify(NotifyConfig) error        // 0600
type Account struct { Label, Cmd string; Builtin bool }

// ---- claude ----
func Argv(cmd string) ([]string, error)               // S§3.1 (cc → cc-profile, LookPath)
func ConfigDir(cmd string) string
func Preflight(ctx context.Context, cmd string, isDefault bool) error // S§1.3 messages
func TestAccount(ctx context.Context, cmd string) (ok bool, msg string)
func ParseLine(line []byte) []Event                   // S§1.7 + hook kinds (§4 TranscriptEvent)
func CopyTranscript(fromCmd, toCmd, cwd, sessionID string) error // S§1.12
type Event struct { Kind string; Text, Name, Error, Reason, SessionID, Model, LimitType, HookEvent string
  Input, Info json.RawMessage; Cost *float64; IsError bool; Tokens *Tokens; ResetsAt *int64; Edits []json.RawMessage; Blocked bool }
type Tokens struct { Input, Cached, Output int64 }
type Usage struct{ /* … */ }
func NewUsage(st *settings.Store, bus *events.Bus, present func() bool) *Usage
func (u *Usage) Start(ctx context.Context)            // 5 s tick; fetch only while present() (S§3.2)
func (u *Usage) Snapshot() map[string]AccountUsage    // key = account cmd

// ---- blubird ----
type Status struct { Installed bool; Version, Latest, InstallPath, Marketplace string; UpdateAvailable bool
  Skills, Hooks []string; Busy string /*""|"installing"|"updating"*/; Error string }
type Manager struct{ /* … */ }
func New(h *home.Home, bus *events.Bus) *Manager
func (m *Manager) Status() Status                     // cached; re-detect on installed_plugins.json mtime
func (m *Manager) Install(ctx context.Context) error  // async job; errs.Conflict if Busy
func (m *Manager) Update(ctx context.Context) error
func (m *Manager) SkillDir(skill string) (string, bool)

// ---- prompts ----
type Source string // "blubird" | "setu"
type RunsIn string // "docs" | "issue" | "repo" | "none"
type Step struct { ID string; Source Source; Skill string; RunsIn RunsIn; Stage string; Label, ArgsHint string }
type Prompt struct { Step, Display, Text string } // Display "/blubird:x a" | "/pr-grind a"; Text = what claude gets
type Registry struct{ /* … */ }
func Load(h *home.Home, version string, bb *blubird.Manager) (*Registry, error) // extract to prompts/<version>/
func (r *Registry) Steps() []Step
func (r *Registry) Step(id string) (Step, bool)
func (r *Registry) Build(stepID, args string) (Prompt, error) // blubird: "/blubird:<skill> <args>"; setu: §9.3
func (r *Registry) Root() string                       // extraction dir = `setu paths`.plugin_root
func (r *Registry) Agent(name string) (body string, tools []string, err error) // "peer-reviewer" | "away-answerer"
func (r *Registry) Available(stepID string) error      // blubird step + blubird missing → errs.Conflict
const Headless, Reentry string                         // §9.4

// ---- gh ----
type Client interface {
  Run(ctx context.Context, args []string, o execx.Opts) execx.Result
  JSON(ctx context.Context, args []string, timeout time.Duration, v any) (execx.Result, error) // G§ gh_json
  GraphQL(ctx context.Context, query string, vars map[string]any, v any) (RateLimit, execx.Result, error)
}
type RateLimit struct { Cost, Remaining int; ResetAt time.Time }
func New() Client
type Auth struct { OK bool `json:"ok"`; Login string `json:"login"`; Error string `json:"error"` }
func NewAuth(c Client) *AuthCache; func (a *AuthCache) Get(ctx context.Context) Auth // TTL 60 s, G§1.3
type PRRef struct { Owner, Repo string; N int }
func ParsePRRef(ctx context.Context, c Client, ref, cwd string) (PRRef, error)
type CI struct { State string `json:"state"`; HeadSHA string `json:"head_sha"`; Failing []CIFail `json:"failing"`; Note string `json:"note,omitempty"`; CIAttempted bool `json:"ci_attempted,omitempty"` }
type CIFail struct { Name, RunID, Link, LogExcerpt string; State, Bucket string } // json snake_case
func CISnapshot(ctx context.Context, c Client, p PRRef) CI
func CIWatch(ctx context.Context, c Client, p PRRef, timeout time.Duration) CI   // G§6.1
type Thread struct { NodeID string; IsResolved, IsOutdated bool; CommentID int64; URL, Path string; Line *int }
func ListThreads(ctx context.Context, c Client, p PRRef) ([]Thread, error)
func ResolveThread(ctx context.Context, c Client, nodeID string) error
func IssuePopup(ctx context.Context, c Client, slug string, n int) (IssueView, error) // G§1.2
func PRPopup(ctx context.Context, c Client, slug string, n int) (PRView, error)
func OpenItems(ctx context.Context, c Client, slug, kind string) ([]OpenItem, error)
func Branches(ctx context.Context, c Client, slug string) (Branches, error)

// ---- products ----
type Registry struct{ /* … */ }
func New(h *home.Home, c gh.Client, bus *events.Bus) *Registry
func (r *Registry) Repos() []Repo
func (r *Registry) RegisterRepo(ctx context.Context, slug, path string) (Repo, error)
func (r *Registry) RemoveRepo(slug string) error
func (r *Registry) Resolve(ctx context.Context, repo string) (path, slug string, err error) // S§5.4 resolve_repo
func (r *Registry) DocsRepo(ctx context.Context, cwd string) (path, slug string, err error)   // G§2.2
func (r *Registry) SlugOf(path string) string
func (r *Registry) Scan(ctx context.Context, roots []string) (ScanResult, error)
func (r *Registry) Check(ctx context.Context) map[string]*string
func (r *Registry) Products() []Product
func (r *Registry) Register(ctx context.Context, docsPath string) (Product, error)
func (r *Registry) RemoveProduct(docsSlug string) error
func (r *Registry) ProductOf(slug string) (Product, bool)
func (r *Registry) Sync(ctx context.Context)                 // called every poll tick
func (r *Registry) PRDs(product string) ([]PRD, error)       // recursive docs/prds/**/*.md in the docs checkout
func (r *Registry) ReadPRD(repo, rel string) (PRDFile, error)
func (r *Registry) CleanupCheck(checkout string, n int, mergedHead string) *CleanupFlags // G§5
func (r *Registry) Cleanup(checkout string, n int, confirm bool, mergedHead string) (removed []string, flags *CleanupFlags, err error)
func (r *Registry) WatchedRepos() []string                   // all product repos with a GitHub slug

// ---- poller ----
type Options struct { Watched func() []string; Hot func(repo string) bool; Now func() time.Time }
type Poller struct{ /* … */ }
func New(c gh.Client, bus *events.Bus, o Options) *Poller
func (p *Poller) Start(ctx context.Context)                  // 5 s tick, G§1.3
func (p *Poller) Snapshot(repo string) Snapshot
func (p *Poller) Poll(ctx context.Context, repo string, full bool) Snapshot // "repoll" after a write
func (p *Poller) MarkViewed(repo string)                     // "*" = every watched repo
func (p *Poller) OnFresh(fn func(repo string, s Snapshot, prev Data))
func (p *Poller) Budget() RateLimit
func MergeBlockers(pr OpenPR, solo bool) string              // G§4.1, "" = none
func MergeReady(pr *OpenPR, g *GrindFact, grindOn, solo bool) bool

// ---- notify ----
type Note struct { ID, Repo, Command, Text, SessionID, Question, Recommended, Error, Step string; Link *Link }
type Service struct{ /* … */ }
func New(h *home.Home, st *settings.Store, bus *events.Bus) *Service
func (s *Service) Notify(event string, n Note)               // async; W§4 compose/suppress; title prefix "setu:"
func (s *Service) SetAway(active func() bool)
func (s *Service) Test(ctx context.Context, channel string) error
func (s *Service) VAPIDPublicKey() string
func (s *Service) Subscribe(sub PushSubscription, ua string) error
func (s *Service) Unsubscribe(endpoint string) error
func Routes(d Deps) []server.Route

// ---- jev ----
type Client struct{ /* … */ }
func New(h *home.Home, enabled func() bool) *Client
func (c *Client) Status() string                             // ok|off|missing
func (c *Client) Ask(ctx context.Context, point, kind, question, text string, options map[string]string, levels []string) Answer // W§7
func (c *Client) Peek(point, kind, question, text string, options map[string]string, levels []string) *Answer
func (c *Client) Start(ctx context.Context)                  // cache flush 60 s
func Commands() []cli.Command                                // setu jev ci-hint|finding-hint

// ---- sessions ----
type RepoResolver interface {
  Resolve(ctx context.Context, repo string) (path, slug string, err error)
  DocsRepo(ctx context.Context, cwd string) (path, slug string, err error)
  SlugOf(path string) string
}
type Notifier interface { Notify(event string, n notify.Note) }
type Deps struct { Home *home.Home; Settings *settings.Store; Prompts *prompts.Registry; Repos RepoResolver
  Bus *events.Bus; Notify Notifier; Usage *claude.Usage; Now func() time.Time; Guards []StartGuard }
type StartGuard func(ctx context.Context, req StartRequest, step prompts.Step, slug string, issue int) error // dispatch/grind add theirs
type Manager struct{ /* … */ }
func New(d Deps) *Manager
func (m *Manager) Reconcile(ctx context.Context) error       // S§1.13
func (m *Manager) Start(ctx context.Context)                 // limit tick 30 s, meta watcher
func (m *Manager) StartSession(ctx context.Context, req StartRequest) (Record, error) // HTTP path, S§5.4 + D1
func (m *Manager) Launch(ctx context.Context, s Spec) (Record, error)                 // internal starts
type Spec struct { Prompt prompts.Prompt; Cwd string; Link *Link; Cmd string /*account cmd; "" = default*/
  Gate bool; Agent string; Instructions []string; Env []string; ExtraFiles []*os.File; AllowedTools []string
  Model, Effort, RunModel, RunEffort string; Batch string; BatchMax int; Kind string; Fields map[string]any }
func (m *Manager) Get(id string) (Record, error)
func (m *Manager) List(f Filter) []Record                    // newest first; f.Answerers=false hides role=away-answerer
func (m *Manager) Update(id string, fn func(*Record) error) (Record, error) // flock RMW; publishes sessions; status dedupe/notify
func (m *Manager) Public(r Record) Session                   // §4 Session
func (m *Manager) Answer(ctx context.Context, id, roundID string, answers map[string]Answer) (Record, error)
func (m *Manager) SendPrompt(ctx context.Context, id, text string, limit int) (state string, err error) // "sent"|"queued"
func (m *Manager) Resume(ctx context.Context, id, text string) error   // answer-style resume (away, panels)
func (m *Manager) ResumeStopped(ctx context.Context, id, accountLabel string) (Record, error)
func (m *Manager) Stop(ctx context.Context, id string) (Record, error)
func (m *Manager) Hold(id string) (Record, error); func (m *Manager) Release(id string) (Record, error)
func (m *Manager) CancelAuto(id string) (Record, error); func (m *Manager) StartNow(ctx context.Context, id string) (Record, error)
func (m *Manager) Rerun(ctx context.Context, id string) (Record, error); func (m *Manager) Dismiss(id string) (Record, error)
func (m *Manager) ClaimAnswer(id, roundID string) (*Round, bool)
func (m *Manager) RestoreRound(id string, r Round) error
func (m *Manager) UpdatePending(id, roundID string, fn func(*Round)) error
func AnswerText(r Round, answers map[string]Answer) (string, error) // S§1.9
func (m *Manager) Stream(id string, offset int64) (events []TranscriptEvent, next int64, err error)
func (m *Manager) FinalText(id string) string                // W§5.3 final_text
func (m *Manager) Alive(id string) bool                      // in-process proc map
func (m *Manager) Limits() map[string]Limit                  // key = account cmd
func (m *Manager) CleanupTargets() []CleanupTarget; func (m *Manager) Cleanup(keys []string) []string
func SetPending(h *home.Home, id string, payload json.RawMessage) (roundID string, err error) // used by `setu ask`
func Routes(d RouteDeps) []server.Route; func Commands() []cli.Command // ask
type Answer struct { Labels []string `json:"labels,omitempty"`; Other *string `json:"other,omitempty"`; None bool `json:"none,omitempty"` }

// ---- grind ----
type LaneOwner interface { ActiveLane(repo string, issue, pr int) (dispatchID string, ok bool); GrindMode(prURL string) (mode string, ok bool) }
type Deps struct { Home *home.Home; GH gh.Client; Sessions *sessions.Manager; Settings *settings.Store; Jev *jev.Client
  Poller *poller.Poller; Notify *notify.Service; Products *products.Registry; Lanes LaneOwner }
type Service struct{ /* … */ }
func New(d Deps) *Service
func (g *Service) Start(ctx context.Context)                  // re-entry 60 s, notify scan 30 s
func (g *Service) Index() []Status
func (g *Service) Get(repo string, pr int) (Status, bool)
func (g *Service) OnFresh(repo string, s poller.Snapshot, prev poller.Data) // autostart W§6.3
func (g *Service) SetIssue(ctx context.Context, repo string, issue int, on bool) error
func (g *Service) SkipCI(ctx context.Context, repo string, pr int) error
func (g *Service) Stop(repo string, pr int) error
func (g *Service) StartGrind(ctx context.Context, repo string, pr int, by string) (sessions.Record, error)
func Resolve(st settings.Settings, channels Channels, checkouts map[string]string, repo string) Reviewers // W§6.4
func Commands() []cli.Command                                  // grind, grind-mode, grind-reviewers, ci, threads
func Routes(d Deps) []server.Route

// ---- dispatch/store (leaf) ----
func Load(h *home.Home, id string) (Dispatch, error); func List(h *home.Home) []Dispatch
func Lock(h *home.Home, id string) (func(), error)
func ActiveLane(h *home.Home, repo string, issue, pr int) (id string, lane Lane, ok bool)
func GrindMode(h *home.Home, prURL string) (mode string, ok bool)

// ---- dispatch ----
func New(d Deps) *Service; func (s *Service) Start(ctx context.Context) // tick 30 s, W§2
func (s *Service) List() []store.Dispatch; func (s *Service) Owned(repo string, issue, pr int) bool // inbox (L8) reads these; dispatch never imports inbox
func (s *Service) Coordinators() []Coordinator
func (s *Service) ActiveLane(repo string, issue, pr int) (string, bool); func (s *Service) GrindMode(prURL string) (string, bool) // satisfies grind.LaneOwner
func Routes(d Deps) []server.Route; func Commands() []cli.Command

// ---- review / away / vault / release ----
func (r *review.Service) Create(ctx context.Context, c CreatePanel) (Panel, error)
func (r *review.Service) Get(id string) (Panel, error); func (r *review.Service) List() []Panel
func (r *review.Service) LensAction(id, lens, action string) (Panel, error); func (r *review.Service) AddRounds(id string, add int) (Panel, error)
func (r *review.Service) Offers() ReviewOffers
func (a *away.Service) Public() Away; func (a *away.Service) Begin(until int64) (Away, error)
func (a *away.Service) End() (Away, error); func (a *away.Service) Dismiss() (Away, error); func (a *away.Service) Change(ch []AwayChange) (AwayChangeResult, error)
func (a *away.Service) Active() bool
func (v *vault.Service) Folders() ([]VaultFolder, error); func (v *vault.Service) Suggest(ctx context.Context, text string) (VaultSuggestion, error); func (v *vault.Service) PRD(folder string) (VaultPRD, error)
func (r *release.Service) Repos(product string) []ReleaseRepo; func (r *release.Service) List(product string) []Release
func (r *release.Service) Cut(ctx context.Context, repo string, dryRun bool) (Release, error)
func (r *release.Service) Grind(ctx context.Context, id string) (Release, error); func (r *release.Service) DraftNote(ctx context.Context, id string) (Release, error)
func (r *release.Service) SaveNote(id, text string) (Release, error); func (r *release.Service) Post(ctx context.Context, id string) (Release, error)
func (r *release.Service) Skip(id string) (Release, error)

// ---- inbox / views ----
type Item = InboxItem /* §4 */
func (b *inbox.Builder) Build(ctx context.Context, product, repo string) InboxList // pure over inputs + rank (G§4.2)
func (v *views.Service) River(ctx context.Context, product string) River
func (v *views.Service) Ops(ctx context.Context, product, repo string) Ops
func (v *views.Service) Me(ctx context.Context) Me
```
Each package ships a `<pkg>test` fake only where a consumer must test without the real dependency: `gh/ghtest.Client` (scripted), `poller/pollertest` (fixed snapshots). For sessions, use the real Manager with fakebin `claude`.

---

## 3. HTTP conventions

- Bind `127.0.0.1:<settings.server.port>` (default **8420**) plus tailscale serve (S§7, W§9). The Host/Tailscale-User-Login/Origin guard applies to every request (403 `text/plain`). HEAD/OPTIONS/TRACE/CONNECT → 405.
- Every `/api/*` response is `application/json; charset=utf-8`. Errors are `{error: string, ...extra}`.
- Request bodies: `Content-Type: application/json*` (else 415), `Content-Length` required (400 `bad Content-Length`), ≤ 65536 (413 `body too large`), a JSON object (400 `body must be a JSON object`). Exception: action POSTs marked "no body" ignore the body entirely.
- Status mapping: `errs.Invalid` 400, `NotFound` 404, `Conflict` 409 (+`id`, `href` in the body when known), `Upstream` 502 (gh/claude/slack failures), anything else 500 `internal error`.
- Path ids: session id `^[0-9]{8}T[0-9]{12}Z-[0-9a-f]{8}$`, dispatch `^[0-9a-f]{12}$`, panel `^p-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$`, release `^r-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$`. A mismatch → 404.
- `{owner}/{name}` path segments must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`. A slug in a query or body must match `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`. Slugs compare case-insensitively and responses use the registered spelling.
- Static: `/` and every non-`/api` GET path that is not a file → `index.html` (SPA). `/assets/*` immutable cache, else `no-cache`. `/sw.js` and `/manifest.webmanifest` come from dist.
- UI-present signal (usage polling, hot repos): an open `/api/events` connection, or any `/api/status` call within 120 s.

---

## 4. Types (TypeScript; JSON field names are exact)

```ts
// ---------- common ----------
type ISO = string;            // RFC 3339 UTC "2026-11-12T09:30:00Z"
type Epoch = number;          // unix seconds
type Slug = string;           // "owner/name"
type IssueKey = string;       // "owner/name#123"
type Link = { owner: string; repo: string; issue: number } | null;
type ApiError = { error: string; id?: string; href?: string; [k: string]: unknown };
type Tone = "" | "c-w" | "c-q" | "c-o" | "c-b";   // prototype tag colours: warn, query/live, ok, bad

/** Server-built action. The UI renders the button and on press calls fetch(method, path, body).
 *  2xx → show `toast`; if `clears`, optimistically drop the row/need. Non-2xx → show ApiError.error. */
type Action = {
  key: string;                 // one keyboard letter, unique within the item
  label: string;
  method: "POST" | "PUT" | "DELETE";
  path: string;                // absolute "/api/..."
  body?: unknown;
  toast: string;
  primary?: boolean;
  clears?: boolean;
  confirm?: string;            // if set, ask with this text first
  open?: string;               // instead of a fetch: UI navigation ("#/sessions/<id>", "#/prd?repo=..&path=..") or an https URL (new tab)
};

// ---------- sessions ----------
type SessionStatus = "starting"|"running"|"waiting"|"limited"|"queued"|"done"|"failed"|"stopped";
type Option = { label: string; description: string; preview?: string };
type Question = { header: string; question: string; multiSelect: boolean; allowFreeText: boolean;
  recommended: string | null; options: Option[] };
type Round = { id: string; status: "pending"; allowFreeText: boolean; held?: boolean;
  answerer?: string | null; risk?: { p: number | null; unknown?: boolean }; questions: Question[] };
type Answer = { labels: string[] } | { other: string } | { none: true };
type Answers = Record<string /* "0".."n-1" */, Answer>;
type Tokens = { input: number; cached: number; output: number };

type Session = {
  id: string; step: string | null; skill: string | null;   // skill "blubird:implement-issue" | "pr-grind" | null (free text)
  kind: string | null;          // "grind" | "release" | "release-note" | "lens" | "panel-root" | "lane" | "coordinator" | null
  title: string;                // issue/PR title from the snapshot when linked, else command's first line ≤120
  command: string; repo: Slug | null; repo_path: string | null; link: Link;
  session_id: string | null; status: SessionStatus;
  model: string | null; effort: string | null; cost: number | null; tokens: Tokens | null;
  started_at: ISO; ended_at: ISO | null; duration_s: number | null;  // ended_at||now − started_at
  waiting: boolean; pending_question: Round | null;
  error: string | null; note: string | null; pending_answer: string | null; queued_prompt: string | null;
  account: string;              // label (or the raw cmd when no longer saved)
  limit_resets_at: Epoch | null; limit_type: string | null; auto_resume: boolean | null;
  hold: boolean; no_repo: boolean; vault_folder: string | null; dismissed: boolean;
  panel: { id: string; role: "root" | "lens"; lens: string | null; state: PanelState } | null;
  dispatch: { id: string; lane: IssueKey } | null;
  hooks: number;                // count of hook events seen (§TranscriptEvent kind "hook")
  resume_command: string | null;
  stalled: string | null;       // why the idle guard let it end unfinished ("ended without finishing or asking"); cleared on resume
};
type SessionStats = { today_count: number; today_cost: number; month_count: number; month_cost: number };

type StartRequest = {
  step?: string;                // registry step id (§9). Exactly one of step | text.
  text?: string;                // free prompt, ≤32000, non-blank, no NUL, not starting "-"
  args?: string;                // appended to the step command; no NUL; for the steps in §9.2, grammar-checked
  repo?: Slug | string;         // registered slug or absolute checkout path. Required unless runs_in "none" or no_repo
  product?: Slug;               // docs repo slug; enough for runs_in "docs"
  issue?: number;               // link; positive int
  no_repo?: boolean; vault_folder?: string;   // vault run (custom text only), S§5.4
  account?: string;             // saved label
  pin_account?: boolean; batch?: string; model?: Model; effort?: Effort;
  lenses?: string[];            // also open a peer-review panel on this run (S§5.4)
  guard?: boolean;              // card guards: live duplicate, dispatch lane owns, open blockers (implement-issue), 30 s identical start
  force?: boolean;              // skip the blocker guard only
};
type Model = "opus" | "sonnet" | "haiku";
type Effort = "low" | "medium" | "high" | "xhigh" | "max";

type TranscriptEvent =
  | { kind: "text"; text: string }
  | { kind: "tool"; name: string; input: unknown }
  | { kind: "result"; cost: number | null; is_error: boolean; text: string | null; tokens: Tokens | null }
  | { kind: "hook"; name: string; event: string; text: string; blocked: boolean };
// hook sources: stream lines type=system with subtype starting "hook" (name=hook_name, event=hook_event, text=output|stdout ≤500);
// guard_ask → {name:"claude-md-guard", event:"PreToolUse", text:"<tool> <path> denied", blocked:true};
// prompt_blocked → {name:"mask-secrets", event:"UserPromptSubmit", text:reason, blocked:true}.
type Transcript = { events: TranscriptEvent[]; offset: number };

type Limit = { limited_until?: Epoch; warning?: { type: string; utilization: number } };
type Meter = { pct: number; resets_at: ISO | null } | null;
type AccountUsage = { label: string; cmd: string; five_hour: Meter; seven_day: Meter; at: Epoch | null; error: string | null; limit: Limit };

// ---------- status ----------
type Status = {
  version: string; boot_id: string;
  blubird: Blubird; gh: { ok: boolean; login: string; error: string };
  usage: AccountUsage[]; away: Away; migrated: boolean;
  poller: { remaining: number | null; reset_at: ISO | null };
};
type Blubird = { installed: boolean; version: string; latest: string; update_available: boolean;
  install_path: string; marketplace: string; skills: string[]; hooks: string[]; busy: "" | "installing" | "updating"; error: string };

// ---------- repos / products ----------
type Repo = { slug: Slug; path: string; product: Slug | null };
type ProductRepo = { name: string; role: string; repo: Slug; path: string; cloned: boolean; conflict?: Slug };
type Product = { docs_repo: Slug; name: string; path: string; repos: ProductRepo[]; error?: string };
// name = docs repo's repos.json "product" key if present, else the docs repo name without "-docs"/"-wiki"
type PRD = { product: Slug; module: string | null; slug: string; title: string;
  status: "Draft" | "In review" | "Approved" | "Done"; path: string; label: string; epic: IssueKey | null };
type PRDFile = { repo: Slug; path: string; text: string; sha: string; branch: string };

// ---------- GitHub popups (shapes as G§1.2) ----------
type IssueView = { number: number; title: string; url: string; state: string; state_reason: string | null; is_pr: boolean;
  merged: boolean; author: string; created_at: ISO; labels: { name: string; color: string }[]; assignees: string[];
  milestone: string | null; body_html: string; comment_count: number;
  comments: { author: string; created_at: ISO; body_html: string }[] };
type PRView = { number: number; title: string; url: string; state: "open"|"closed"|"merged"|"draft"; conflict: boolean;
  head: string; base: string; head_sha: string; author: string; body_html: string;
  files: { path: string; additions: number; deletions: number; status: string; patch: string | null; patch_cut?: boolean }[];
  commits: { sha: string; message: string; author: string }[];
  conversation: { kind: "comment" | "review"; author: string; at: ISO; state?: string; body_html: string }[];
  checks: { name: string; bucket: "green" | "red" | "pending"; link: string }[] };
type OpenItem = { number: number; title: string; labels: string[]; updated_at: ISO; draft: boolean; url?: string };

// ---------- River ----------
type StageId = "prd" | "tasks" | "refine" | "implement" | "review" | "release" | "notify";
type Card = {
  id: string;                   // stable: "prd:<slug>" | "epic:<key>" | "issue:<key>" | "pr:<key>" | "session:<id>" | "release:<id>" | "repo:<slug>" | "coord:<run>"
  stage: StageId; title: string; meta: string; tag: string; tone: Tone;
  need: boolean; need_kind: "Question" | "Approval" | "Failed" | "Release" | "Decide" | null;
  live: boolean; skill: string; repo: string;     // repo display name (last slug segment)
  log: string[];                // ≤8 lines, newest last
  ask: { session_id: string; round: Round } | null;   // UI answers via POST /api/sessions/{id}/answer
  note: string | null;          // release note text when need_kind "Release"
  links: { issue?: string; pr?: string; session?: string; prd?: string };
  actions: Action[];
};
type River = { product: Slug; stale: Slug[]; fetched_at: ISO | null;
  stages: { id: StageId; name: string; skills: string; hot: boolean; cards: Card[] }[] };

// ---------- Inbox ----------
type InboxGroup = "block" | "answer" | "decide" | "fix" | "setup" | "wait";
type InboxItem = {
  key: string; group: InboxGroup; type: InboxType; kind: string;  // kind = display tag ("Question","Approval","Failed","Release",...)
  title: string; repo: Slug | null; at: ISO | null; urgency: number | null;
  session_id?: string; round?: Round; note?: string; detail?: string[];
  links: { issue?: string; pr?: string; session?: string; prd?: string };
  actions: Action[];
};
type InboxType = "gh_auth" | "blubird_missing" | "question" | "prd_approval" | "session_failed" | "limited" | "queued"
  | "review_cap" | "review_approved" | "grind_paused" | "needs_cleanup" | "pr_conflict" | "pr_ready" | "release_note"
  | "dispatch_needs" | "dispatch_held" | "dispatch_merge" | "dispatch_limited" | "dispatch_done" | "away_summary" | "repo_unpublished";
type InboxList = { items: InboxItem[]; stale: Slug[]; count: number /* items not in group "wait" */ };

// ---------- Releases ----------
type ReleaseStage = "cut" | "grind" | "merge" | "notify" | "done" | "skipped" | "failed" | "dry_run";
type Release = { id: string; repo: Slug; head: string; base: string; stage: ReleaseStage; dry_run: boolean;
  pr: number | null; pr_url: string | null; thread: string | null; grind: GrindStatus | null;
  cut_session: string | null; note_session: string | null; note: string | null; note_posted_at: ISO | null;
  note_permalink: string | null; merged_at: ISO | null; error: string | null; dry_run_dir: string | null;
  created_at: ISO; updated_at: ISO; actions: Action[] };
type ReleaseRepo = { repo: Slug; name: string; head: string; base: string; ahead: number | null; prs_waiting: number | null;
  last_release: { pr: number; merged_at: ISO } | null; open: string | null /* release id in flight */; checked_at: ISO | null; actions: Action[] };

// ---------- Ops / Me ----------
type SessionBrief = { id: string; status: SessionStatus; started_at: ISO; ended_at: ISO | null; cost: number | null };
type OpsRow = { step: string; label: string; scope: "each repo" | "docs repo" | "any repo"; summary: string;
  targets: { repo: Slug; last: SessionBrief | null; note: string }[]; actions: Action[] };
type Ops = { product: Slug; rows: OpsRow[] };
type Me = { day_end: { date: string; reconciled: boolean; missing_days: number; last: SessionBrief | null };
  weekly: { week: number; drafted: boolean; last: SessionBrief | null };
  usage: AccountUsage[]; cost: SessionStats; actions: Action[] };

// ---------- grind ----------
type GrindState = "none" | "idle" | "running" | "paused" | "approved" | "done";
type GrindStatus = { repo: Slug; pr: number; state: GrindState; mode: "deep" | "simple" | null; rounds: number;
  reason: string | null; thread: string | null; updated: ISO | null; next_poll: ISO | null; session: string | null };

// ---------- dispatch (W§2; public view) ----------
type LaneStage = "queued"|"implementing"|"grinding"|"merge_gate"|"conflict_fix"|"awaiting_merge"|"followups"|"closed"|"skipped";
type DispatchSettings = { max: number; grind: "off"|"simple"|"full"; ci: "wait"|"defer"|"ignore"; auto_merge: boolean;
  skip_approval: boolean; feature_branch: string | null; base_branch: string | null; model: string | null;
  effort: Effort | null; account: string | null; max_cost: number | null };
type Lane = { key: IssueKey; repo: Slug; n: number; title: string; deps: IssueKey[]; stage: LaneStage; pr: number | null;
  needs_you: string | null; held: string | null; gate: string | null; skip_reason: string | null; paused: boolean;
  paused_by: "dispatch" | null; hold_merge: boolean; limited_until: Epoch | null; started_at: Epoch | null;
  ended_at: Epoch | null; session: string | null; usage: { cost: number; tokens: Tokens | null; seconds: number } };
type Dispatch = { id: string; epic: IssueKey | null; issues?: IssueKey[]; title: string;
  state: "running" | "paused" | "done" | "cancelled"; settings: DispatchSettings; lanes: Lane[];
  totals: { lanes: number; closed: number; cost: number }; created_at: Epoch; ended_at: Epoch | null;
  events?: { at: Epoch; lane: IssueKey | null; kind: string; text: string }[] };
type DispatchPlan = { title: string; waves: IssueKey[][]; lanes: { key: IssueKey; title: string; refined: boolean; deps: IssueKey[] }[]; warnings: string[] };
type Coordinator = { run: string /* run dir basename */; repo: Slug; source: string; destination: string; session: string | null;
  live: boolean; queue: { issue: number; state: string; title: string }[]; claims: number[]; prs: Record<string, unknown>;
  poll: { calls: number; last: Epoch; result: string; every: number } | null; events: string[] /* last 20 lines of events.log */ };

// ---------- away (W§3) ----------
type Away = { active: boolean; until: Epoch | null; started: Epoch | null; decisions: number; held: number;
  summary: { started: Epoch; ended: Epoch; held: number; log: AwayLog[] } | null };
type AwayLog = { at: Epoch; kind: "answer" | "held" | "retry"; sid: string; link: Link; repo: Slug | null; command: string;
  question: string; picked: string; id?: string; risk?: number; by?: "recommended" | "opus";
  questions?: (Question & { picked: string[]; why: string })[]; answerer?: string; cost?: number; changed?: boolean; reason?: string };

// ---------- peer review (W§5) ----------
type PanelState = "running" | "approved" | "cap reached" | "failed";
type Panel = { id: string; repo: Slug; artifact: string; lenses: string[]; root_session: string | null; round: number;
  max_rounds: number; dropped: string[]; failed: string[]; state: PanelState; reason: string | null;
  phase: "waiting_root" | "lenses" | "root" | "done"; lens_sessions: Record<string, string>;
  status: { approved: number; total: number; lenses: Record<string, "failed" | "approve" | "changes" | "waiting"> } };
type ReviewOffers = { default: string[]; max_rounds: number; kinds: Record<string, string[]> };
type ReviewConfig = { max_rounds: number; default_lenses: string[]; lenses: Record<string, string>;
  shipped: { max_rounds: number; default_lenses: string[]; lenses: Record<string, string> }; overridden: boolean };

// ---------- settings (on-disk names; D13) ----------
type RepoSettings = { auto_grind: boolean; slack_channel: string; reviewers: string[] | null;
  release_head?: string; release_base?: string;                 // default "staging" → "master"
  /* GET only: */ path?: string | null; grind_path?: "slack" | "github" | null; channel_invalid?: boolean };
type Settings = {
  claude_label: string; commands: { label: string; cmd: string; builtin?: boolean }[]; default: string;
  repos: Record<Slug, RepoSettings>;
  slack_channels: { id: string; name: string }[];
  reviewers: { id: string; name: string; slack_id: string; github_login: string }[]; active_reviewers: string[];
  vault_dir: string | null; grind_mode: "deep" | "simple"; use_jev: boolean;
  idle_guard: boolean;                                           // default true; absent reads as true
  run_model: Model | null; run_effort: Effort | null;
  grind_limits: { max_rounds: number; poll_interval: number; max_wait: number; max_idle_waits: number;
    stuck_seen: number; ci_timeout: number; ci_poll: number };     // defaults 10, 60, 1500, 4, 2, 1200, 30
  release_note: { channel_name: string; channel_id: string; cc: { name: string; slack_id: string }[]; suffix: string };
    // default {"dc-supports","C06RSFFRUFM",[Ashique UAY0MVDHT, Najmul U01012AA4FL, Abir U067P3ADDDM],"vai"}
  server: { port: number; tailscale: boolean; tailscale_https_port: 443 | 8443 | 10000; allow_hosts: string[] };
  /* GET only: */ jev_installed?: boolean; bot_label?: string | null;
};
type NotifySettings = { matrix: Record<NotifyEvent, { browser: boolean; push: boolean; mac: boolean }>;
  events: { key: NotifyEvent; label: string; group: string }[]; public_url: string;
  mac: { available: boolean; notifier: string; clickable: boolean }; push: { subscriptions: number } };
type NotifyEvent = "waiting"|"failed"|"dispatch"|"panel-cap"|"pr-ready"|"needs-cleanup"|"grind-paused"|"grind-done"|"done"|"afk"|"release";
type PushSubscription = { endpoint: string; keys: { p256dh: string; auth: string } };

// ---------- vault ----------
type VaultFolder = { project: string; feature: string | null; path: string };
type VaultSuggestion = { project: string; feature: string; new_project: boolean; new_feature: boolean; why: string };
type VaultPRD = { exists: boolean; status: string | null; title: string | null; folder: string };
```

---

## 5. Endpoints

`Pkg` = the owning package. "—" body = no body read. A 404 for an unknown id is implied on every `{id}` route.

### 5.1 Status, events, registry
| Method | Path | Request | Response | Codes | Pkg |
|---|---|---|---|---|---|
| GET | `/api/health` | — | `{ok:true}` | 200 | server |
| GET | `/api/status` | — | `Status` | 200 | cmd wiring (handler in `views`) |
| GET | `/api/events` | — | SSE (§6) | 200 | server |
| GET | `/api/registry` | — | `{steps: (Step & {command, available:boolean, reason?:string})[]}` (§9 order) | 200 | prompts |

### 5.2 Sessions (sessions)
| Method | Path | Request | Response | Codes |
|---|---|---|---|---|
| GET | `/api/sessions?limit=200&before=<id>&status=<csv>&repo=<slug>&step=<id>` | — | `{sessions: Session[], stats: SessionStats, limits: Record<string, Limit>}` | 200, 400 |
| POST | `/api/sessions` | `StartRequest` | `Session` | 201; 400; 409 `{error,id,href}`; 502 preflight/spawn |
| GET | `/api/sessions/{id}` | — | `Session` | 200 |
| GET | `/api/sessions/{id}/stream?offset=N` | — | `Transcript` (S§2.6) | 200, 400 `bad offset` |
| POST | `/api/sessions/{id}/answer` | `{round_id: string, answers: Answers}` | `Session` | 200; 400/409/413/415/500 as S§1.9 |
| POST | `/api/sessions/{id}/prompt` | `{text}` ≤4000 | `{state:"sent"}` / `{state:"queued"}` | 200 / 202; 400; 409 |
| POST | `/api/sessions/{id}/stop` | — | `Session` | 200; 409 |
| POST | `/api/sessions/{id}/resume` | `{account?: label}` (optional body) | `Session` | 200; 400; 409 |
| POST | `/api/sessions/{id}/{cancel-auto\|hold\|release\|start-now\|dismiss}` | — | `Session` | 200; 409 |
| POST | `/api/sessions/{id}/rerun` | — | `Session` (new) | 201; 400; 409; 502 |
| GET | `/api/sessions/cleanup` | — | `{items:{key,label,repo,flags:string[]}[]}` | 200 |
| POST | `/api/sessions/cleanup` | `{keys: string[]}` | `{removed: string[]}` | 200; 400 |

Start semantics: S§5.2–5.4 with `step` in place of `command`. `runs_in` routing: `docs` → `DocsRepo(repo|product)`; `issue`/`repo` → the resolved checkout; `none` → `vault_dir` if it exists, else `$HOME` (no slug). A blubird step while blubird is missing → 409 `blubird is not installed`. Guards when `guard:true`, in order:
1. A live session with the same step family, issue and repo → 409 `<step> already running for o/r#N (session <id>)`.
2. A dispatch lane owns the issue or PR → 409 `dispatch <id> owns o/r#N`.
3. `implement-issue` with open blockers and no `force` → 409 `#N is blocked by #a, #b`.
4. An identical (step, args, repo) start within 30 s → 409 `just started (session <id>)`.

Guard 1 always applies to `implement-issue` and `pr-grind` (S§5.4), even without `guard`.

### 5.3 Repos, products, GitHub (products, gh, poller)
| Method | Path | Request | Response | Codes | Pkg |
|---|---|---|---|---|---|
| GET | `/api/repos` | — | `{repos: Repo[], can_browse: boolean, scan_roots: string[]}` | 200 | products |
| POST | `/api/repos` | `{slug, path}` | `{repo: Repo, repos: Repo[]}` | 200; 400 | products |
| DELETE | `/api/repos/{owner}/{name}` | — | `{repos: Repo[]}` | 200; 404 | products |
| POST | `/api/repos/scan` | `{roots?: string[]}` | `{added: Repo[], duplicates: Repo[], repos: Repo[]}` | 200; 400 | products |
| POST | `/api/repos/check` | `{}` | `{problems: Record<Slug, string \| null>}` | 200 | products |
| POST | `/api/repos/browse` | `{start?: string}` | `{path: string \| null}` | 200; 403 | products |
| POST | `/api/repos/{owner}/{name}/cleanup` | `{issue: number, confirm: true}` | `{removed: string[]}` | 200; 400; 409 `#N's PR is not merged` | products |
| GET | `/api/repos/{owner}/{name}/open?kind=issue\|pr` | — | `{items: OpenItem[]}` | 200; 400; 502 | gh |
| GET | `/api/repos/{owner}/{name}/branches` | — | `{branches: string[], default: string}` | 200; 502 | gh |
| GET | `/api/products` | — | `{products: Product[]}` | 200 | products |
| POST | `/api/products` | `{path: string}` | `Product` | 201; 400 | products |
| DELETE | `/api/products/{owner}/{name}` | — | `{products: Product[]}` | 200 | products |
| GET | `/api/products/{owner}/{name}/prds` | — | `{prds: PRD[]}` | 200 | products |
| GET | `/api/prd?repo=<slug>&path=docs/prds/...md` | — | `PRDFile` | 200; 400 | products |
| POST | `/api/repos/create` | `{name, parent: abs dir, vault_folder?}` | `{repo, repos}` | 201; 400; 409 exists; 502 git | products: `git init -b main`, README (+ the vault folder's PRD.md at `docs/prds/<feature>.md`), first commit, registered as `local/<name>` |
| POST | `/api/repos/publish` | `{slug: "local/…", owner, name, private}` | `{repo, repos}` | 200; 400; 404; 502 gh | products: `gh repo create owner/name --private\|--public --source <dir> --remote origin --push`, then the checkout becomes `owner/name` |
| GET | `/api/github/owners` | — | `{owners: string[]}` (gh user, then orgs) | 200; 502 | products |
| PUT | `/api/prd` | `{repo, path, text, base_sha}` | `PRDFile` (after the commit) | 200; 400; 404; 409 file changed since `base_sha` (`{sha}`); 502 git | products: writes the file and commits only it on the current branch (`docs(prd): edit <path> in setu`), never pushes |
| GET | `/api/issues/{owner}/{name}/{n}` | — | `IssueView` | 200; 400; 404; 502 | gh |
| GET | `/api/pulls/{owner}/{name}/{n}` | — | `PRView` | 200; 400; 404; 502 | gh |
| POST | `/api/issues/{owner}/{name}/{n}/comment` / `/api/pulls/.../comment` | `{text}` ≤65536 | `{ok:true, url}` | 200; 400; 502 | gh |
| POST | `/api/issues/{owner}/{name}/{n}/state` | `{state:"open"\|"closed", reason?:"completed"\|"not_planned"}` | `{ok:true, state}` | 200; 400; 502 | gh (+repoll) |
| POST | `/api/pulls/{owner}/{name}/{n}/state` | `{state:"open"\|"closed"}` | `{ok:true, state}` | 200; 400; 502 | gh (+repoll) |
| POST | `/api/pulls/{owner}/{name}/{n}/merge` | `{sha: 40-hex}` | `{ok:true}` | 200; 400; 502 | gh (`--merge --match-head-commit`, never squash; human only) |
| POST | `/api/epics/{owner}/{name}/{n}/close` | `{}` | `{ok:true, closed: number[]}` | 200; 502 | gh |
| POST | `/api/refresh` | `{repo?: Slug, product?: Slug}` | `{ok:true}` (async full poll) | 202 | poller |

### 5.4 Views (views, inbox)
| Method | Path | Request | Response | Codes |
|---|---|---|---|---|
| GET | `/api/river?product=<docs slug>&repo=` (`repo` of no product: a River of that repo alone, without PRD and "commits ahead" cards; a repo of a product shows that product) | — | `River` (marks the shown repos viewed; every card's `log` and `actions` are arrays, never null) | 200; 400 unknown product or repo |
| GET | `/api/inbox?product=&repo=` | — | `InboxList` (marks viewed `*`) | 200 |
| GET | `/api/features?product=` | — | `FeatureList`: per PRD the stage (draft, review, approved, tasks, building, shipped), bay (you, go, running, shipped), next-step line and actions, epic, its open issues (state and row actions) and closed ones, counts, newest panel on the PRD file, the dispatch owning the epic, sessions. Sorted by bay | 200; 400 unknown product |
| GET | `/api/changes?repo=` | — | `{stale, issues: FeatureIssue[], pending: FeatureSession[]}`: open issues that belong to no epic in every registered repo (or one), with feature-issue states and row actions; `pending` = live `small-change` and `report-bug` runs | 200 |
| GET | `/api/ops?product=&repo=` (`repo` of no product: its repo steps run on itself, docs repo steps "needs a product" with no action) | — | `Ops` | 200; 400 unknown product or repo |
| GET | `/api/me` | — | `Me` | 200 |

### 5.5 Grind, review, dispatch, coordinator, away, vault, jev
| Method | Path | Request | Response | Codes | Pkg |
|---|---|---|---|---|---|
| GET | `/api/grinds?repo=` | — | `{grinds: GrindStatus[]}` | 200 | grind |
| POST | `/api/grinds` | `{repo, pr}` | `Session` | 201; 409 live/owned | grind |
| POST | `/api/grinds/issue` | `{repo, issue, on: boolean}` | `{ok:true}` | 200; 400; 502 | grind |
| POST | `/api/grinds/{owner}/{name}/{pr}/skip-ci` | — | `{state:"running"}` | 200; 409 | grind |
| POST | `/api/grinds/{owner}/{name}/{pr}/stop` | — | `GrindStatus` | 200 | grind |
| GET | `/api/review` | — | `{panels: Panel[]}` | 200 | review |
| POST | `/api/review` | `{repo, artifact (abs path), lenses: string[], root_session?: string, after_root?: boolean}` | `Panel` | 201; 400; 409 | review |
| GET | `/api/review/{panel}` | — | `Panel` | 200 | review |
| POST | `/api/review/{panel}/lens` | `{lens, action:"rerun"\|"drop"}` | `Panel` | 200; 400; 409 | review |
| POST | `/api/review/{panel}/rounds` | `{add: 1..5}` | `Panel` | 200; 400; 409 | review |
| GET | `/api/review/offers` | — | `ReviewOffers` | 200 | review |
| GET | `/api/dispatches` | — | `{dispatches: Dispatch[]}` | 200 | dispatch |
| POST | `/api/dispatches` | `{epic?: IssueKey\|string, issues?: IssueKey[], settings?: Partial<DispatchSettings>}` (one of epic/issues) | `Dispatch` | 201; 400; 409 `{error,id}` | dispatch |
| POST | `/api/dispatches/plan` | same as create | `DispatchPlan` | 200; 400 | dispatch |
| GET | `/api/dispatches/{id}` | — | `Dispatch` (with events) | 200 | dispatch |
| POST | `/api/dispatches/{id}/settings` | `Partial<DispatchSettings>` | `Dispatch` | 200; 400 | dispatch |
| POST | `/api/dispatches/{id}/state` | `{state:"running"\|"paused"\|"cancelled", now?: boolean}` | `Dispatch` | 200; 400 | dispatch |
| POST | `/api/dispatches/{id}/lane` | `{lane: IssueKey, action: "pause"\|"resume"\|"retry"\|"skip"\|"merge"\|"hold"\|"unhold"\|"send"\|"unblock", text?}` (`skip` settles the lane: clears needs-you, held and gate, sets `ended_at`; `unblock` drops the lane's skipped blockers so it can start; `retry` on a skipped lane queues it again) | `Dispatch` | 200; 400 | dispatch |
| POST | `/api/dispatches/{id}/lanes` | `{issues: IssueKey[]}` (River "Add to dispatch") | `Dispatch` | 200; 400; 409 | dispatch |
| POST | `/api/dispatches/{id}/{retry-failed\|seen}` | `{undo?: boolean}` for seen | `Dispatch` | 200 | dispatch |
| POST | `/api/dispatches/{id}/end` | `{action:"open-pr"\|"qa"\|"grind-pr"}` | `Dispatch` | 200; 400 | dispatch |
| GET | `/api/coordinators` | — | `{coordinators: Coordinator[]}` | 200 | dispatch |
| POST | `/api/coordinators/{run}/stop` | — | `{ok:true}` (runs `<blubird>/skills/project-coordinator/scripts/coordinator.sh stop <run dir>`) | 200; 404; 502 | dispatch |
| POST | `/api/away` | `{until: Epoch}` | `Away` | 200; 400 | away |
| POST | `/api/away/stop` / `/api/away/dismiss` | — | `Away` | 200 | away |
| POST | `/api/away/change` | `{changes: {id: string, answers: Answers}[]}` | `{sent: string[], queued: string[], errors: {sid, ids, error}[]}` | 200; 400; 409 | away |
| GET | `/api/vault/folders` | — | `{vault: string, folders: VaultFolder[]}` | 200; 400 no vault | vault |
| GET | `/api/vault/prd?folder=` | — | `VaultPRD` | 200; 400 | vault |
| POST | `/api/vault/suggest` | `{text}` | `VaultSuggestion` | 200; 400; 502 | vault |
| POST | `/api/jev/route` | `{text}` ≤20,000 characters | `{route: "feature"\|"small"\|"bug"\|null, p: number\|null, status: "ok"\|"off"\|"missing"\|"no_answer"\|"failed"\|"unreadable"\|"unsure"}` (route set only on `ok`; `unclear` or p < 0.4 → `unsure`; not cached or counted) | 200; 400; 413 body over 64 KiB (as every route; reachable under 20,000 characters only with 4-byte characters); 415 | jev |

### 5.6 Releases (release)
| Method | Path | Request | Response | Codes |
|---|---|---|---|---|
| GET | `/api/releases?product=` | — | `{repos: ReleaseRepo[], releases: Release[]}` (releases newest first, done ≤30 days) | 200 |
| POST | `/api/releases` | `{repo: Slug, dry_run?: boolean}` | `Release` (stage `cut`, starts `release-pr`) | 201; 409 one in flight per repo `{error,id}` |
| POST | `/api/releases/{id}/grind` | — | `Release` (starts `pr-grind <thread\|pr url>` unless live) | 200; 409 |
| POST | `/api/releases/{id}/note` | — | `Release` (starts or redoes the `release-note` draft) | 200; 409 posted |
| PUT | `/api/releases/{id}/note` | `{text}` ≤8000 | `Release` | 200; 409 posted |
| POST | `/api/releases/{id}/post` | — | `Release` (posts once; stage `done`) | 200; 409 already posted / no note; 502 slack (the release keeps `error`, **no retry**) |
| POST | `/api/releases/{id}/skip` | — | `Release` (stage `skipped`) | 200 |

### 5.7 Settings, blubird, notifications (settings, claude, blubird, notify, review)
| Method | Path | Request | Response | Codes | Pkg |
|---|---|---|---|---|---|
| GET | `/api/settings` | — | `Settings` (view) | 200 | settings |
| PUT | `/api/settings` | `Partial<Settings>` | `Settings` | 200; 400 | settings |
| POST | `/api/settings/test-account` | `{label}` | `{ok: boolean, message: string}` | 200; 400 | claude |
| GET | `/api/settings/review` | — | `ReviewConfig` | 200 | review |
| PUT | `/api/settings/review` | `{max_rounds, default_lenses, lenses}` or `{reset:true}` | `ReviewConfig` | 200; 400 | review |
| GET | `/api/settings/notify` | — | `NotifySettings` | 200 | notify |
| PUT | `/api/settings/notify` | `{public_url?: string, cell?: {event, channel:"browser"\|"push"\|"mac", on: boolean}}` | `NotifySettings` | 200; 400 | notify |
| POST | `/api/settings/notify/test` | `{channel: "push"\|"mac"}` | `{ok: boolean, error?: string}` | 200; 400 | notify |
| GET | `/api/push/key` | — | `{public_key: string}` (VAPID, base64url) | 200 | notify |
| POST | `/api/push/subscription` | `PushSubscription` | `{ok:true}` | 200; 400 | notify |
| DELETE | `/api/push/subscription` | `{endpoint}` | `{ok:true}` | 200 | notify |
| GET | `/api/blubird` | — | `Blubird` | 200 | blubird |
| POST | `/api/blubird/install` / `/api/blubird/update` | — | `Blubird` (busy set) | 202; 409 busy; 502 `claude` missing | blubird |

Install runs `claude plugin marketplace add blubird-interactiveltd/agentic-workflow` and then `claude plugin install blubird@agentic-workflow`. Update runs `claude plugin marketplace update agentic-workflow` and then `claude plugin update blubird@agentic-workflow`; an "unknown command" result counts as success. Each step has a 300 s timeout. On finish the server publishes `products{kind:"blubird"}` and a toast.

---

## 6. SSE: `GET /api/events`

Headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`. On connect the server first sends `retry: 3000` and then `event: hello`. Every 15 s it sends the comment `: ping`. Each event is `id: <n>\nevent: <name>\ndata: <json>\n\n`. `Last-Event-ID` is ignored: the UI refetches everything on every `hello`. All payloads are small: the UI refetches the named resource and never renders from the payload, except `toast`.

| Event | Payload | Fires when | UI refetches |
|---|---|---|---|
| `hello` | `{version, boot_id, resync: boolean}` | connect; after the server dropped events for a slow client (`resync:true`) | everything visible |
| `sessions` | `{id, status, change:"record"\|"stream"\|"removed"}` | any `Manager.Update`; a `meta.json` change written by `setu ask` (seen by the meta watcher within 1 s); stream growth (throttled to 1 per s per session); cleanup | `/api/sessions`; `/api/sessions/{id}` + `stream?offset` if open; River/Me (debounced 1 s) |
| `inbox` | `{count}` | the inbox's (key, content-hash) set changes. It is recomputed 500 ms (debounced) after any sessions/products/dispatch/usage{away} event. | `/api/inbox` (+ nav badge from `count`) |
| `products` | `{kind:"snapshot"\|"registry"\|"release"\|"grind"\|"review"\|"blubird"\|"coordinator"\|"prd", repo?: Slug}` | poller fresh-with-change (data hash differs) or a stale flip; repos/products change; release, grind index, panel, coordinator file change (10 s scan); blubird job state | `/api/river`, `/api/releases`, `/api/ops`, `/api/products`, `/api/blubird` as relevant to `kind` |
| `dispatch` | `{id, change:"record"\|"removed"}` | dispatch save/archive | `/api/dispatches[/id]` |
| `usage` | `{kind:"usage"\|"limits"\|"gh"\|"away"\|"settings"}` | meter refresh; limits change; gh auth flips; away begin/end/tick-log; settings save | `/api/status` (+ `/api/settings` on `settings`) |
| `toast` | `{id: number, event: NotifyEvent \| "info" \| "error", title, body, path: string /* "#/..." */, level:"info"\|"warn"\|"error"}` | notify browser channel (W§4.4 replaces the `ui_feed` ring); finished background jobs (blubird install, release post) | none: show it, `path` = click target |

---

## 7. On-disk layout (`~/.setu`, override `SETU_HOME`)

Atomic writes and `flock` on `<file>.lock` everywhere (G "shared helpers"). Corrupt JSON goes through `BackupIfCorrupt`. A missing file reads as empty. All paths are relative to the home.

| Path | Owner | Schema / notes | Compat |
|---|---|---|---|
| `.migrated` | home | empty marker; created after the first copy of `OldDataDir()` | new |
| `sessions/<id>/meta.json` | sessions (+ `setu ask` child, under `sessions/<id>/.lock`) | S§2.2 fields + `step`, `args`, `kind`, `agent` (name), `role`, … JSON indent 2 + `\n` | **must** read old records; `harness`/codex fields ignored |
| `sessions/<id>/stream.jsonl`, `stderr.log` | the child process (append) | raw stream-json / stderr | same |
| `ui_settings.json` | settings | `Settings` minus GET-only keys | same + new keys `grind_limits`, `release_note`, `server`, `repos[].release_head/base` |
| `issue_grind.json` | settings | `{ "owner/repo"(lower): { "<n>": bool } }` | same |
| `ui.json` (0600; looser mode → ignored + warning) | settings/notify | `{ntfy:{server,topic,token|user,password}, public_url, channels:{event:{browser,ntfy,mac,push}}}` | same file |
| `push.json` (0600) | notify | `{vapid_public, vapid_private, subject:"mailto:setu@localhost", subscriptions:[{endpoint, keys:{p256dh,auth}, ua, created_at}]}`; a 404/410 from the push service removes the subscription | new |
| `checkouts.json` | products | `{ "owner/repo": "/abs" }` (`local/<name>` allowed) | same |
| `products.json` | products | `{ "<docs slug>": "/abs" }` | same |
| `channels.json` | grind (read; Settings never writes it) | W§6.4 shape; `<channels>` in `setu paths` | same |
| `config.json` | review | `{peer_review:{max_rounds, default_lenses, lenses:{name:{prompt}}}}` overrides | same |
| `pr-grind/<owner>-<repo>-<pr>.md` (+ `.lock`) | grind (and the grind CLI from the child) | W§13.2 #3: header keys `owner repo number thread author base reviewer reviewers unlogged learned reviewers-last paused done next-poll poll-since ci-seen dispatch-due queued-push ci-attempt mode channel started updated idle-waits last-seen`; then `## Round <n>` sections with `- finding:`/`- fixed:`/`- rebutted:`/`- note:`/`- jev-ci-hint:`/`- jev-finding-hint:` lines; `thread: github` is valid | same files |
| `pr-grind/<owner>-<repo>-<pr>.last.json` | grind CLI | last evaluated round (finding fingerprints) | new |
| `grind_notified.json` | grind | sorted list of keys (W§6.3) | same |
| `dispatches/<id>.json` (+`.lock`, `.store.lock`, `archive/`) | dispatch/store | W§2.1 (`runner:"headless"`, `workspace` ignored) | same |
| `afk.json` | away | W§3.1 | same |
| `peer-review/<panel>/panel.json`, `round-<n>/<lens>.md`, `peer-review/asks/ui-*.md` | review | W§5.2 | same |
| `jev_cache.json` | jev | W§7 | same |
| `releases/<id>.json` (+`.lock`) | release | `Release` fields minus `actions`/`grind` + `cut_session`, `note_file`; id `r-YYYYMMDDTHHMMSSZ-<6hex>` | new |
| `releases/<id>/note.md` | release (written by the release-note draft session; edited by PUT) | Slack mrkdwn | new |
| `release-pr/<owner>-<repo>-<date>/` | release-pr prompt (dry run) | W§12.1 | same |
| `prompts/<version>/<name>/SKILL.md`, `scripts/*`, `prompts/<version>/agents/*.md` | prompts | extracted on start when the dir is missing; `<version>` = `setu version`; old versions are kept (live sessions may use them), versions >5 back are deleted | new |
| `setu.log` | cmd (launchd stdout/stderr) | | new |
| `bootstraps/`, `ui_opened.json`, `shares*`, `restart.*`, `migrated-dev-workflow` | — | ignored, never read or deleted | dropped |

External (read-only): `${CLAUDE_CONFIG_DIR:-~/.claude}/plugins/installed_plugins.json` (blubird). `~/.claude/project-coordinator/{<slug>.json, claims/<slug>/<issue>/run, runs/<slug>/<stamp>/{config.json, queue.tsv (issue\tstate\ttitle), prs.json, poll_stats.json, events.log, control/}}` (dispatch; runs started by a setu session are matched via `config.json.repo` and the session's start time). `~/.claude*/projects/<slug>/<session>.jsonl` (transcript copy on account rebind).

---

## 8. CLI

`setu <verb>`. Exit 64 for usage errors unless stated otherwise. JSON output is indent 2 + `\n`. Verbs that run inside a child session find the home through `SETU_HOME`.

| Verb | Flags / args | Stdout | Exit | Pkg |
|---|---|---|---|---|
| `serve` (alias `ui`) | `[--port N] [--allow-host H]... [--no-tailscale] [--tailscale-port 443\|8443\|10000]` (flags override settings.server) | log lines | 0 on signal; 1 port in use (`port N is already in use by PID p (name)`) | cmd |
| `version` | — | `setu <semver> (<commit>)` | 0 | cmd |
| `paths` | — | `{plugin_root, prompts_dir, data_dir, pr_grind_dir (created), channels, checkouts, home}` (`plugin_root` == `prompts_dir` == `prompts/<version>`) | 0 | cmd |
| `ask` | `[--json STR]` (else stdin) | `RECORDED <rid>. The question is now with the human. End your turn immediately; the answer arrives as your next message: Answer to <rid>: {...}` | 0; 2 no session (`setu ask needs a setu session (SETU_SESSION); interactive runs use AskUserQuestion`) or another round waiting (S§1.9 text); 5 bad payload | sessions |
| `ci status <pr>` | `[--watch] [--timeout 1200]` | `CI` JSON | 0 (any state); 64 unresolvable ref | gh |
| `threads list <pr>` | `[--open-only] [--for-comment ID]` | `[{node_id,is_resolved,is_outdated,comment_id,url,path,line}]` | 0; 1 read failure | gh |
| `threads resolve <node_id>...` | — | `resolved <id>` per id | 0; 1 if all failed | gh |
| `grind-mode` | `[--pr URL]` | `deep` \| `simple` | 0 | grind |
| `grind-reviewers` | `--pr URL [--strict]` | `{path, channel, mentions, logins, unlogged, skip}` | 0; 1 `{"error":…}` with `--strict` | grind |
| `grind start <pr>` | `[--thread URL] [--channel ID] [--reviewer LOGIN\|copilot] [--mode deep\|simple]` | `GrindStatus` | 0; 3 draft/closed; 64; 70 external failure | grind |
| `grind wait <pr>` | `[--once] [--timeout S]` | round JSON `{round, reviewers:[…], findings:[{fp,path,line,body,author,new}], clean, approved}` (0) or `{reason}` | 0 round landed; 10 stop (approved, or clean in deep mode); 12 timeout / nothing yet with `--once` (writes `next-poll`); 20 round cap; 21 stuck finding; 22 third-party human comment; 23 reviewer silent; 24 PR not open; 40 done; 41 paused | grind |
| `grind ci <pr>` | `[--watch] [--timeout 1200]` | `CI` + `ci_attempted` | 0 green; 1 red; 2 pending; 3 conflict; 4 error | grind |
| `grind threads <pr>` | as `threads list` | same | same | grind |
| `grind retrigger <pr>` | — | `{posted: "slack"\|"github", url?}` | 0; 32 queued-push set; 33 CI not green | grind |
| `grind record <pr> <kind> [text...]` | kind ∈ `fixed rebutted note ci-attempt queued unqueue jev-ci-hint jev-finding-hint` | — | 0; 30 ci-attempt exists for the head SHA | grind |
| `grind pause <pr> <reason...>` | — | — | 0 | grind |
| `grind done <pr> <reason...>` | (reason starting `approved` = approved) | — | 0; 31 queued-push set | grind |
| `grind status <pr>` | `[--json]` (read-only, no network) | `GrindStatus` or a text line | 0 | grind |
| `grind mode` / `grind reviewers` | = `grind-mode` / `grind-reviewers` | | | grind |
| `dispatch plan\|start\|ls\|show\|set\|pause\|resume\|cancel\|lane\|watch\|retry-failed\|end\|archive\|doctor` | W§2.6 (no `--runner/--workspace`); `start` launches `setu serve` detached when port 8420 is closed (log `setu.log`) | W§2.6 shapes | 0; 1 doctor problems; 5 ValueError/Conflict | dispatch |
| `jev ci-hint --file F` / `jev finding-hint --file F` | — | W§7 | always 0 | jev |
| `blubird status\|install\|update` | — | `Blubird` JSON | 0; 1 failure | blubird |
| `review lenses` | — | `ReviewConfig` (for the peer-review prompt) | 0 | review |

`<pr>` everywhere: a URL, `owner/repo#N`, `owner/repo N`, or bare `N` (cwd's repo), as G§6.1.

---

## 9. Built-in prompt registry

### 9.1 Steps (`Registry.Steps()` order = palette order)

| step id | source | skill | runs_in | stage (River/Ops/Me) | args |
|---|---|---|---|---|---|
| `create-prd` | blubird | create-prd | docs | prd | free text, a PRD path, or `<path> — the team has reviewed it; approve it` (Approval action) |
| `map-prds` | blubird | map-prds | docs | prd · ops | `[file or folder ...]` |
| `create-tasks` | blubird | create-tasks | docs | tasks | `<PRD path>` |
| `small-change` | blubird | create-tasks | repo | refine | `<finding>` |
| `refine-issues` | blubird | refine-issues | issue | refine | `<epic \| issues>` (repo = the epic's/issues' repo) |
| `reproduce-bug` | blubird | reproduce-bug | issue | refine | `<issue \| symptoms>` |
| `implement-issue` | blubird | implement-issue | issue | implement | `<issue \| epic>` |
| `after-merge` | blubird | implement-issue | issue | implement | `<n> (PR #p for issue #n is merged: …)` (W§2.4) |
| `verifier-locally` | blubird | verifier-locally | issue | implement | free |
| `project-coordinator` | blubird | project-coordinator | docs | implement | `<issues link \| n> [--destination L] [--max N]` |
| `pr-review` | blubird | pr-review | issue | review | `<PR \| branch \| range> [--fix]` |
| `peer-review` | setu | peer-review | repo | review | `[--lenses a,b] <artifact>` \| `--root <panel> <artifact>` |
| `pr-grind` | setu | pr-grind | issue | review | `<PR url \| thread url> [--channel ID] [--reviewer L]` |
| `release-pr` | setu | release-pr | repo | release | `[--dry-run] [<head> <base>]` |
| `release-note` | setu | release-note | none | notify | `<pr-url> [channel:<name>] [cc:<a,b>] [--draft <file>]` |
| `agentic-onboard` | blubird | agentic-onboard | repo | ops | `[--dev]` |
| `ci-optimize` | blubird | ci-optimize | repo | ops | — |
| `security-sweep` | blubird | security-sweep | docs | ops | `[repo name ...]` |
| `docs-updater` | blubird | docs-updater | repo | ops | `[full] [issue]` |
| `skill-feedback` | blubird | skill-feedback | repo | ops | `<feedback> \| reconcile …` |
| `day-end-reconcile` | blubird | day-end-reconcile | none | me | — |
| `weekly-review` | blubird | weekly-review | none | me | — |

`runs_in`: `docs` = the product's Documentation Repo (G§2.2 `docs_repo`). `issue` = the repo holding the target issue/PR (the UI passes the card's repo; an issue URL in args overrides it, S§5.4). `repo` = any registered repo the user picks. `none` = no repo (vault_dir or `$HOME`, no link). GitHub-only steps (`create-tasks, small-change, refine-issues, implement-issue, after-merge, pr-grind, pr-review, release-pr, project-coordinator`) refuse `local/*` slugs (S§5.4).

### 9.2 Arg checks (400 on failure; all args: no NUL/newline, not starting `-` unless the step's grammar allows)
- `implement-issue`, `after-merge`: first token `#?\d+` → also sets `link.issue`.
- `refine-issues`: `#?\d+([\s,]+#?\d+)*` → space-joined.
- `pr-grind`: `#?\d+` (expanded to the PR URL of `repo`) or `https://\S+`, then the optional flags.
- `release-pr`, `release-note`, `peer-review`, `pr-review`, `project-coordinator`: allow leading `--` flags from their grammar.
- `create-tasks`: a path under `docs/prds/` ending `.md`.

### 9.3 Building the prompt
- blubird: `Text = Display = "/blubird:<skill> <args>"` (trimmed). It is never rewritten.
- setu: `Display = "/<skill> <args>"`. `Text = "Base directory for this skill: <Root()>/<skill>\n\n<SKILL.md body without frontmatter>\n\nARGUMENTS: <args>"`. Prompt source files use `setu <verb>` (no `aiw`) and `<plugin_root>/<skill>/scripts/...` paths. Every reference to `../../guides`, `self-improve.md` and `Skill` hand-offs to plugin-qualified names is removed from the embedded text. `release-pr` hands off by running `setu grind start <pr> --thread <url>` and ends with the `SETU-RELEASE:` line (D10).
- Agents: `prompts/agents/peer-reviewer.md` and `prompts/agents/away-answerer.md` (frontmatter `tools:` line = AllowedTools, split on `", "`).

### 9.4 Fixed texts
- `Headless`: `Headless run: ask via setu ask. AskUserQuestion is not available: wherever a skill says to ask the user with AskUserQuestion, run \`setu ask --json '<the AskUserQuestion input>'\` instead, then end your turn; the answer arrives as your next message. Never call ScheduleWakeup: a pending wakeup keeps this process alive, and the UI cannot take an answer until it exits.`
- `Reentry`: W§6.2 text with `aiw ui timer` → `setu timer` and `aiw ask` → `setu ask`.
- Golden argv: S§1.4 with D4. Lens: `RESTRICTED --allowedTools <T> --append-system-prompt <peer-reviewer body> --model opus <prompt>`. Answerer: `RESTRICTED --allowedTools <T> --append-system-prompt <away-answerer body> --model opus --effort medium <prompt>`. Resume adds `\n\n<Headless>` to the same single append value.

---

## 10. Build phases and acceptance tests

Test harness (`internal/testutil/fakebin`): `Install(t, dir)` writes fake `claude`, `gh`, `slackcli`, `jev`, `terminal-notifier`, `security`, `tailscale` executables (one small Go program built once per test run, with symlinks) and prepends `dir` to `PATH`. Behaviour comes from `FAKEBIN_FIXTURES=<dir>/rules.json`: `[{bin, args_prefix: string[], args_contains?: string, stdin_contains?: string, stdout_file?|stdout?, stderr?, exit, sleep_ms?, exec?: string[] /* run another command, e.g. setu ask */, once?: boolean}]`. The first match wins. An unmatched call → exit 99 + stderr `fakebin: no rule`. Every call is appended to `<dir>/calls.jsonl` `{bin, args, cwd, env:{SETU_*,AIW_*}, stdin}`. Fake `claude auth status --json` defaults to `{"loggedIn":true}`. Fixture streams live in `testdata/claude/*.jsonl` (port `fixtures/claude_guard_ask.jsonl` and `claude_secret_block.jsonl`; add a recorded blubird hook stream). No test touches the network or a real `$HOME` (`t.Setenv("HOME", t.TempDir())`, `SETU_HOME`).

### 10.1 Phases

| Phase | Parallel groups | Gate to next |
|---|---|---|
| **P0** (1 dev, first) | `go.mod`, `cmd/setu` skeleton, `errs`, `execx`, `home` (+Migrate), `events`, `cli`, `server` core (guard, Decode/Handle, SSE, static, SPA), `web` embed stub, `fakebin`. Web: Vite/Preact scaffold + `web/src/api/types.ts` transcribed from §4 + a fetch client + an SSE client. | P0 tests green; `setu serve` serves an empty SPA + `/api/health` + `/api/events` |
| **P1** (6 in parallel) | **A** `settings` + `claude` · **B** `gh` (+ ci/threads verbs) + `poller` · **C** `products` · **D** `blubird` + `prompts` (+ writing the 4 built-in prompts and 2 agents) · **E** `notify` + `jev` · **F** web: shell, rail/tabs/drawer/split, Appearance, palette, keyboard map, all 7 screens on a mock server (`web/mock/` fixtures typed by `types.ts`) | each package's tests green |
| **P2** (3 in parallel) | **G** `sessions` (+ `setu ask`; the biggest; may start in P1 against the §2 signatures of settings/claude/prompts) · **H** `grind` CLI half (state file, rails, `wait/ci/record/retrigger/status`, resolver; needs gh) · **I** `review` + `vault` | sessions golden argv + lifecycle tests green |
| **P3** (5 in parallel) | **J** `grind` server half (re-entry tick, autostart, notify scan, routes) · **K** `dispatch` + `dispatch/store` + coordinators · **L** `release` · **M** `away` · **N** `inbox` + `views` + `/api/status` | each package's tests green |
| **P4** (2 in parallel) | **O** wiring `main.go`, e2e suite, `make install`, launchd plist, migration from a copy of a real old data dir · **P** web against the real server: SSE refetch map (§6), actions runner, transcript view, answer forms, Settings forms, PWA + push subscribe | e2e green; manual run on this machine |

### 10.2 Acceptance tests per package (Go `go test`, table tests)

| Package | Must pass |
|---|---|
| home | migrate copies once + marker, never deletes the old dir, idempotent; `UpdateJSON` under contention (2 goroutines + 1 subprocess) loses no write; corrupt file backed up as `.corrupt-<ts>`; `TryLock` held by a child fd blocks others |
| events | fan-out to N subscribers; slow subscriber gets `resync`; unsubscribe frees |
| server | Host guard matrix (loopback ok, tailnet host needs login header, bad Origin 403, missing Host 403); 405 for HEAD/OPTIONS; body rules 400/413/415; error kind → status; SPA fallback; `/assets` cache header; path traversal `%2e%2e` and `%252e` → 404; SSE hello/ping/event framing |
| settings | S§4.1 validation table (labels, cmds, channels, reviewers, repos keys); partial save keeps omitted keys; legacy `auto_grind` migration; old file with `harness`/codex keys loads; new keys default; `ui.json` 0644 ignored |
| claude | `ParseLine` over every S§1.7 row + the hook kinds; `tokens_of` edge cases; `Argv` `cc` rewrite + not-on-PATH; preflight messages (not logged in, timeout, default vs other); usage keychain service name; expired token → `re-login needed`; usage fetch only while present (fake HTTP via `httptest`, URL injectable) |
| blubird | detect from `installed_plugins.json` (respects `CLAUDE_CONFIG_DIR`), missing → `installed:false`; latest from the marketplace manifest; install/update argv sequence; busy → 409; "unknown command" on `plugin update` tolerated |
| prompts | registry covers every §9.1 row; `Build` for blubird/setu shapes; frontmatter stripped; no `aiw ` left in embedded prompts (grep test); extraction idempotent; old-version pruning keeps 5; `Agent` tools parsed; blubird step unavailable → Conflict |
| gh | `gh_json` scalar/empty/non-JSON; CI: conflict, `no checks`→green, nonzero exit with JSON read, pending>red>green, error, `--watch` stops/cap note, log excerpt 4000; threads pagination, `--open-only`, `--for-comment` string/int; resolve partial failure exit codes; popups 404 vs 502, patch caps; PR ref parsing all forms |
| poller | every G§10 "pinned by tests" bullet; cross-repo `Ref` for parent/sub-issues/blockers; Projects v2 `Status` read when present, derived otherwise (G§3 mapping); `OnFresh` gets prev; publishes `products{snapshot}` only on change |
| products | G§10 products bullets; nested PRD discovery `docs/prds/<module>/<feature>.md` + status/slug/title regexes; docs-repo pointer errors; scan budget/dup; merge cleanup bullets (never outside `.worktrees/`, never HEAD branch, never remote) |
| notify | ntfy publisher parity (auth Bearer>Basic, UA `setu (ntfy publisher)`, 0600 rule, env overrides `SETU_NTFY_*` then `AIW_NTFY_*`, 5 s timeout, `httptest` server) ; matrix defaults (W§4.1 minus prd-comment/pipeline + `release`); compose titles `setu:` ASCII; suppression (answerer, grind `done`, away); mac argv (never script text); push: VAPID keygen once, 0600, 410 removes the subscription (`httptest` push service); toast published on the browser channel |
| jev | redaction table; cache key/TTL/2000 cap; ceiling 500/h, `capped`; `off` never execs; ci-hint/finding-hint fallbacks, always exit 0; `/api/jev/route` statuses, 0.4 cut-off, never cached or counted, 400/415 |
| sessions | **golden argv** (S§1.4 table, with D4/D5); env contains `SETU_SESSION`, `AIW_UI_SESSION`, `SETU_HOME`, no `CLAUDE_PLUGIN_DATA`; full lifecycle via fake claude: done, failed (rc), limited (event + regex), waiting via `setu ask` exec rule (child writes meta, server publishes + notifies once), answer → resume argv, guard relay Approve/Deny applies the edit, mask-secrets block, asked-but-no-round failure, 30 s reap; stop kills the process group; batch cap 3 + release; limit tick auto-resume + stagger; queued prompt delivery; hold/release; rerun replays `request`; restart reconcile (alive fingerprint, dead, waiting watcher); answer validation matrix (S§1.9 codes); `setu ask` exit codes 0/2/5 and idempotent same-signature round; legacy record (`/ai-workflow:implement-issue 12`) → `step:"implement-issue"`; start guards D1 order; `runs_in` routing for docs/issue/repo/none |
| grind | state header parse/write (`thread: github` valid, `done:` under a round terminal, `## Round` count); every `wait` exit code from fixture review sequences; `ci` exit codes; `record ci-attempt` 30; `retrigger` 32/33; `done` 31; `status --json` offline; resolver W§6.4 table; `grind-mode` dispatch override; re-entry tick decision order (S§1.14), MAX_GRINDS 2, lock fd inherited; autostart draft→ready only; notify first scan silent; skip-ci/stop |
| review | verdict regex table; `advance` states; phases incl. held lens; corrupt `panel.json`; lens rerun/drop conflicts; add_rounds restore on failure; lens argv uses the agent body (D4) |
| dispatch | port W§13.3 list: `step` rule table (every rule 1–8), gates incl. CI-none grace, merge error handling (conflict, not up to date, N fails), strand/cycle, outbox, archive 30 d, retry_failed, cost cap pause, facts from a truncated snapshot, inbox rows, CLI shapes (`ls`, `watch`, `doctor` exit 1); coordinator reader over a fixture run dir (queue.tsv states `ok`/`blocked:#a,#b`) and the stop argv |
| away | W§3 tests: hold words, risk p=0.49/0.5/unknown, cost caps $10/$2, two-attempt rule, 10 min timeout, reply parse table, retry ladder 120/600/1800/3600, change answers (conflict, revert on refusal), summary push once |
| vault | `valid_folder` table; folders listing; suggest parse (first `{…}`, sanitising) with fake claude; PRD info |
| release | cut → parses `SETU-RELEASE:` from the final text → stage grind; grind approved → merge; fake `gh pr view` MERGED → notify + draft session started once; PUT note; post runs `slackcli messages send --recipient-id <id> --message-file <f> --json` **exactly once** even with 2 concurrent POSTs; a post failure keeps `error`, no retry, 409 on repost; dry run → `dry_run` + dir; one open release per repo (409); `ReleaseRepo.ahead` from fake compare |
| inbox | G§4.2 table for every kept type + new `prd_approval`, `release_note`, `blubird_missing`, `away_summary`; repo filter; stale list; rank order; dispatch-owned rows dropped; every item has ≥1 action and the action paths exist in the route table (test walks the mux) |
| views | River: each stage's card derivation from fixture snapshots + sessions + grind + releases (PRD Draft/In review → prd; epic with unrefined children → tasks; Backlog/bug → refine; Ready/In progress/live → implement; non-draft open PR/grind/pr-review → review; repo ahead>0 or release in cut/grind/merge → release; release notify → notify); `need` matches inbox; Ops rows per §9.1 stage `ops`; Me: reconciled today, ISO week drafted, month cost |
| cmd/e2e | temp `SETU_HOME` + fakebin: `setu serve` on a random port; register a product; start `implement-issue` → waiting via `setu ask` → SSE `sessions` + `inbox` → answer → done; release flow end to end; migration from `testdata/olddata/` (sessions, settings, pr-grind files, dispatches) renders `/api/sessions`, `/api/settings`, `/api/grinds` |
| web | `tsc --noEmit`; vitest: action runner (fetch/open/confirm/clears), SSE refetch map (§6 table), keyboard map (prototype HINTS + `1-7`, `:`/⌘K, `.`, `s`, `L`, `?`, `a/b/c` answers, action keys); smoke render of the 7 screens from mock fixtures in both looks × both layouts |
