package dispatch

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/jev"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
	"github.com/masnun-siam/setu/internal/settings"
)

// Timing of the server side (W§2.7).
const (
	TickSeconds        = 30
	SyncSeconds        = 300
	OpenRecheckSeconds = 300
	sendLimit          = 32000
)

// Sessions is what dispatch needs of sessions.Manager.
type Sessions interface {
	Launch(ctx context.Context, s sessions.Spec) (sessions.Record, error)
	Get(id string) (sessions.Record, error)
	Update(id string, fn func(*sessions.Record) error) (sessions.Record, error)
	SendPrompt(ctx context.Context, id, text string, limit int) (string, error)
	Stop(ctx context.Context, id string) (sessions.Record, error)
	List(f sessions.Filter) []sessions.Record
}

// PromptBuilder is satisfied by prompts.Registry.
type PromptBuilder interface {
	BuildIn(stepID, args, repo string) (prompts.Prompt, error)
	Available(stepID string) error
}

// Snapshots is satisfied by poller.Poller.
type Snapshots interface {
	Snapshot(repo string) poller.Snapshot
}

// Accounts is satisfied by settings.Store.
type Accounts interface {
	Account(label string) (settings.Account, bool)
	Default() settings.Account
}

// Notifier is satisfied by notify.Service.
type Notifier interface {
	Notify(event string, n notify.Note)
}

// JevAsker is satisfied by jev.Client.
type JevAsker interface {
	Status() string
	Ask(ctx context.Context, point, kind, question, text string, options map[string]string, levels []string) jev.Answer
}

// GrindPlan is how a repo's PRs get reviewed (W§6.4, as far as dispatch cares): Path is "slack" or
// "github" ("" = unresolved), Skip says why lanes skip grinding, Channel is the Slack channel id.
// The wiring adapts grind.Resolve to it.
type GrindPlan struct{ Path, Skip, Channel string }

// Deps wires a Service. Home and GH are required; the rest may be nil in the CLI process.
type Deps struct {
	Home      *home.Home
	GH        gh.Client
	Sessions  Sessions
	Prompts   PromptBuilder
	Snapshots Snapshots
	Accounts  Accounts
	Notify    Notifier
	Bus       *events.Bus
	Jev       JevAsker
	Grind     func(repo string) GrindPlan
	Login     func(ctx context.Context) string  // the signed-in gh login ("" unknown)
	SkillDir  func(skill string) (string, bool) // blubird.Manager.SkillDir
	IdleGuard func() bool                       // the idle_guard setting; nil reads as off
	Merge     func(ctx context.Context, repo string, pr int, sha string) (ok bool, errText string)
	Now       func() time.Time
	CoordRoot string // default ~/.claude/project-coordinator (tests)
}

// The real types satisfy the interfaces above.
var (
	_ Sessions      = (*sessions.Manager)(nil)
	_ PromptBuilder = (*prompts.Registry)(nil)
	_ Snapshots     = (*poller.Poller)(nil)
	_ Accounts      = (*settings.Store)(nil)
	_ Notifier      = (*notify.Service)(nil)
	_ JevAsker      = (*jev.Client)(nil)
)

// Service ticks the dispatches and serves their API.
type Service struct {
	d Deps

	mu          sync.Mutex
	issueState  map[string]issueState
	truncWarned map[string]bool
	archivedAt  time.Time
	tickMu      sync.Mutex
}

type issueState struct {
	state string
	at    time.Time
}

// New builds the service.
func New(d Deps) *Service {
	if d.Now == nil {
		d.Now = time.Now
	}
	return &Service{d: d, issueState: map[string]issueState{}, truncWarned: map[string]bool{}}
}

func (s *Service) now() float64 { return epoch(s.d.Now()) }

func logf(format string, a ...any) { log.Printf("dispatch: "+format, a...) }

func (s *Service) publish(id, change string) {
	if s.d.Bus != nil {
		s.d.Bus.Publish(events.TDispatch, map[string]any{"id": id, "change": change})
	}
}

// ---- the store, as the API names it ----

// List is every dispatch, newest first.
// List is for readers: the records are shared with the store cache and must not be modified.
func (s *Service) List() []store.Dispatch { return store.ListShared(s.d.Home) }

// Get is one dispatch.
func (s *Service) Get(id string) (store.Dispatch, error) { return store.Load(s.d.Home, id) }

// Owned reports a live lane of a running or paused dispatch for the issue or PR (inbox drops the
// generic rows it would duplicate).
func (s *Service) Owned(repo string, issue, pr int) bool {
	_, _, ok := store.ActiveLane(s.d.Home, repo, issue, pr)
	return ok
}

// ActiveLane satisfies grind.LaneOwner.
func (s *Service) ActiveLane(repo string, issue, pr int) (string, bool) {
	id, _, ok := store.ActiveLane(s.d.Home, repo, issue, pr)
	return id, ok
}

// GrindMode satisfies grind.LaneOwner.
func (s *Service) GrindMode(prURL string) (string, bool) { return store.GrindMode(s.d.Home, prURL) }

// Repos lists the repos of live dispatch lanes (active or queued): the poller keeps them fresh.
func (s *Service) Repos() []string {
	set := map[string]bool{}
	var out []string
	for _, d := range store.ListShared(s.d.Home) {
		if !store.Live(d.State) {
			continue
		}
		for _, x := range d.Lanes {
			if (store.Active(x.Stage) || x.Stage == store.StQueued) && !set[x.Repo] {
				set[x.Repo] = true
				out = append(out, x.Repo)
			}
		}
	}
	return out
}

// mutate is the locked load-modify-save used by the API.
func (s *Service) mutate(id string, fn func(d *store.Dispatch) error) (store.Dispatch, error) {
	unlock, err := store.Lock(s.d.Home, id)
	if err != nil {
		return store.Dispatch{}, err
	}
	defer unlock()
	d, err := store.Load(s.d.Home, id)
	if err != nil {
		return d, err
	}
	if err := fn(&d); err != nil {
		return d, err
	}
	if err := store.Save(s.d.Home, &d); err != nil {
		return d, err
	}
	s.publish(id, "record")
	return d, nil
}

// ---- creating ----

// CreateRequest is POST /api/dispatches.
type CreateRequest struct {
	Epic     string
	Issues   []string
	Settings map[string]any
}

func (s *Service) checkAccount(st store.Settings) error {
	if st.Account != nil && s.d.Accounts != nil {
		if _, ok := s.d.Accounts.Account(*st.Account); !ok {
			return errs.Invalid("account must be a label saved in Settings")
		}
	}
	return nil
}

// prepare checks the request and returns the settings.
func (s *Service) prepare(r CreateRequest) (store.Settings, error) {
	if (r.Epic == "") == (len(r.Issues) == 0) {
		return store.Settings{}, errs.Invalid("give either epic or issues")
	}
	st, err := ApplySettings(store.Defaults(), r.Settings)
	if err != nil {
		return st, err
	}
	if err := s.checkAccount(st); err != nil {
		return st, err
	}
	if len(r.Issues) > 0 {
		if _, _, err := ParseIssues(r.Issues); err != nil {
			return st, err
		}
		if err := noFeatureBranch(st); err != nil {
			return st, err
		}
	}
	return st, nil
}

func uniq(in []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, x := range in {
		if !seen[x] {
			seen[x] = true
			out = append(out, x)
		}
	}
	return out
}

func repoSet(kids []Child) []string {
	seen := map[string]bool{}
	var out []string
	for _, c := range kids {
		if !seen[c.Repo] {
			seen[c.Repo] = true
			out = append(out, c.Repo)
		}
	}
	return out
}

// Plan previews a dispatch without creating it (POST /api/dispatches/plan).
func (s *Service) Plan(ctx context.Context, r CreateRequest) (PlanView, error) {
	st, err := s.prepare(r)
	if err != nil {
		return PlanView{}, err
	}
	var res Resolved
	if len(r.Issues) > 0 {
		res, err = s.ResolveIssues(ctx, uniq(r.Issues), true)
	} else {
		res, err = s.ResolveEpic(ctx, r.Epic, true)
	}
	if err != nil {
		return PlanView{}, err
	}
	return s.Preview(ctx, res, st), nil
}

// Create resolves the epic or pick, cuts the feature branch if asked, and records the dispatch.
// The server's tick runs it.
func (s *Service) Create(ctx context.Context, r CreateRequest) (store.Dispatch, error) {
	st, err := s.prepare(r)
	if err != nil {
		return store.Dispatch{}, err
	}
	if s.d.Prompts != nil {
		if err := s.d.Prompts.Available("implement-issue"); err != nil {
			return store.Dispatch{}, err
		}
	}
	var res Resolved
	list := len(r.Issues) > 0
	if list {
		res, err = s.ResolveIssues(ctx, uniq(r.Issues), false)
		if err == nil && len(res.Children) == 0 {
			err = errs.Invalid("none of the picked issues is open")
		}
	} else {
		res, err = s.ResolveEpic(ctx, r.Epic, false)
		if err == nil && len(res.Children) == 0 {
			err = errs.Invalid("%s has no open child issues", *res.Epic)
		}
	}
	if err != nil {
		return store.Dispatch{}, err
	}
	repos := repoSet(res.Children)
	if miss := s.MissingBase(ctx, repos, store.Str(st.BaseBranch)); len(miss) > 0 {
		return store.Dispatch{}, errs.Invalid("%s", strings.Join(miss, "; "))
	}
	if fb := store.Str(st.FeatureBranch); fb != "" {
		for _, repo := range repos {
			if _, err := s.EnsureFeatureBranch(ctx, repo, fb, store.Str(st.BaseBranch)); err != nil {
				return store.Dispatch{}, err
			}
		}
	}
	now := s.now()
	d := store.Dispatch{ID: store.NewID(), Epic: res.Epic, Title: res.Title, Runner: "headless", Settings: st,
		State: store.Running, Lanes: map[string]*store.Lane{}, Events: []store.Event{}, CreatedAt: now}
	if list {
		d.Issues = res.Issues
	}
	SyncLanes(&d, res.Children, now)
	d.AddEvent("", "started", fmt.Sprintf("%d lanes", len(d.Lanes)), now)
	if err := store.Create(s.d.Home, &d); err != nil {
		return store.Dispatch{}, err
	}
	s.publish(d.ID, "record")
	return d, nil
}

// AddLanes puts hand-picked issues into an existing dispatch (River "Add to dispatch").
func (s *Service) AddLanes(ctx context.Context, id string, refs []string) (store.Dispatch, error) {
	repo, _, err := ParseIssues(refs)
	if err != nil {
		return store.Dispatch{}, err
	}
	cur, err := store.Load(s.d.Home, id)
	if err != nil {
		return cur, err
	}
	if cur.State == store.Cancelled {
		return cur, errs.Conflict("dispatch "+id+" is cancelled", map[string]any{"id": id})
	}
	if len(cur.Issues) > 0 && !strings.EqualFold(cur.Repo(), repo) {
		return cur, errs.Invalid("all issues must be in one repo, got %s and %s", cur.Repo(), repo)
	}
	res, err := s.ResolveIssues(ctx, uniq(refs), false)
	if err != nil {
		return cur, err
	}
	if len(res.Children) == 0 {
		return cur, errs.Invalid("none of the picked issues is open")
	}
	return s.mutate(id, func(d *store.Dispatch) error {
		if d.State == store.Cancelled {
			return errs.Conflict("dispatch "+id+" is cancelled", map[string]any{"id": id})
		}
		unlock, err := store.StoreLock(s.d.Home)
		if err != nil {
			return err
		}
		defer unlock()
		for _, c := range res.Children {
			k := store.Key(c.Repo, c.N)
			if owner := store.OwnerOf(s.d.Home, k); owner != "" && owner != id {
				return errs.Conflict(k+" is already a lane of dispatch "+owner, map[string]any{"id": owner})
			}
		}
		now := s.now()
		if len(d.Issues) > 0 {
			d.Issues = uniq(append(d.Issues, res.Issues...))
		} else {
			d.Added = uniq(append(d.Added, res.Issues...))
		}
		for _, k := range SyncLanes(d, res.Children, now) {
			d.AddEvent(k, "lane", "joined the dispatch", now)
		}
		return nil
	})
}

// ---- API edits ----

// SetSettings is a live edit; it takes effect at the next tick.
func (s *Service) SetSettings(id string, patch map[string]any) (store.Dispatch, error) {
	if _, ok := patch["base_branch"]; ok {
		return store.Dispatch{}, errs.Invalid("base_branch is fixed at start")
	}
	return s.mutate(id, func(d *store.Dispatch) error {
		st, err := ApplySettings(d.Settings, patch)
		if err != nil {
			return err
		}
		if err := s.checkAccount(st); err != nil {
			return err
		}
		if len(d.Issues) > 0 {
			if err := noFeatureBranch(st); err != nil {
				return err
			}
		}
		d.Settings = st
		d.AddEvent("", "settings", fmtSettings(patch), s.now())
		return nil
	})
}

// SetState moves the whole dispatch.
func (s *Service) SetState(id, state string, stopNow bool) (store.Dispatch, error) {
	return s.mutate(id, func(d *store.Dispatch) error { return SetState(d, state, stopNow, s.now()) })
}

// LaneAction is the user's action on one lane.
func (s *Service) LaneAction(id, lane, action, text string) (store.Dispatch, error) {
	return s.mutate(id, func(d *store.Dispatch) error {
		k := lane
		if !strings.Contains(k, "#") { // an issue number
			for key, x := range d.Lanes {
				if fmt.Sprint(x.N) == lane {
					k = key
				}
			}
		}
		return ApplyLaneAction(d, k, action, text, s.now())
	})
}

// RetryFailed retries every failed, held or needing lane.
func (s *Service) RetryFailed(id string) (store.Dispatch, []string, error) {
	var keys []string
	d, err := s.mutate(id, func(d *store.Dispatch) error { keys = RetryFailed(d, s.now()); return nil })
	return d, keys, err
}

// RequestEnd queues an end action.
func (s *Service) RequestEnd(id, action string) (store.Dispatch, error) {
	return s.mutate(id, func(d *store.Dispatch) error { return RequestEnd(d, action, s.now()) })
}

// Seen marks a finished dispatch as seen in the inbox (or undoes it).
func (s *Service) Seen(id string, undo bool) (store.Dispatch, error) {
	return s.mutate(id, func(d *store.Dispatch) error { d.SeenDone = !undo; return nil })
}

// Archive moves finished dispatches ended more than days ago to dispatches/archive/.
func (s *Service) Archive(days float64) []string {
	moved := store.ArchiveOld(s.d.Home, s.now(), days)
	for _, id := range moved {
		s.publish(id, "removed")
	}
	return moved
}

// ---- Start: the tick loop ----

// Start runs the tick every TickSeconds until ctx ends (a panic in a tick is logged, never fatal).
func (s *Service) Start(ctx context.Context) {
	go func() {
		t := time.NewTicker(TickSeconds * time.Second)
		defer t.Stop()
		for {
			func() {
				defer func() {
					if r := recover(); r != nil {
						logf("tick panicked: %v", r)
					}
				}()
				s.TickAll(ctx)
			}()
			select {
			case <-ctx.Done():
				return
			case <-t.C:
			}
		}
	}()
}

// TickAll archives (once a day) and ticks every busy dispatch.
func (s *Service) TickAll(ctx context.Context) {
	s.tickMu.Lock()
	defer s.tickMu.Unlock()
	if s.d.Now().Sub(s.archivedAt) > 24*time.Hour {
		s.archivedAt = s.d.Now()
		s.Archive(store.ArchiveDays)
	}
	for _, d := range store.ListShared(s.d.Home) {
		if ctx.Err() != nil {
			return
		}
		if busy(&d) {
			if _, err := s.TickOne(ctx, d.ID); err != nil {
				logf("%s tick failed: %v", d.ID, err)
			}
		}
	}
}

// busy: a finished dispatch still needs ticks for end actions, outboxes and a QA session's new issues.
func busy(d *store.Dispatch) bool {
	if store.Live(d.State) {
		return true
	}
	outbox := false
	for _, x := range d.Lanes {
		outbox = outbox || len(x.Outbox) > 0
	}
	switch d.State {
	case store.Done:
		return len(d.EndReqs) > 0 || d.QA != nil || outbox
	case store.Cancelled:
		return outbox
	}
	return false
}

// TickOne loads one dispatch under its lock, gives it facts and ticks it. It returns the new events.
func (s *Service) TickOne(ctx context.Context, id string) ([]store.Event, error) {
	unlock, err := store.Lock(s.d.Home, id)
	if err != nil {
		return nil, err
	}
	defer unlock()
	d, err := store.Load(s.d.Home, id)
	if err != nil {
		return nil, err
	}
	if !busy(&d) {
		return nil, nil
	}
	now := s.now()
	if d.State != store.Cancelled && now-d.SyncedAt >= SyncSeconds {
		d.SyncedAt = now
		kids, err := s.reread(ctx, &d)
		if err != nil {
			logf("%s: cannot re-read the %s: %v", id, map[bool]string{true: "issues", false: "epic"}[len(d.Issues) > 0], err)
		} else {
			for _, k := range SyncLanes(&d, kids, now) {
				d.AddEvent(k, "lane", "joined the dispatch", now)
			}
		}
	}
	facts := map[string]Facts{}
	for k, x := range d.Lanes {
		if store.Active(x.Stage) || x.Stage == store.StQueued {
			if f, ok := s.laneFacts(ctx, x); ok {
				facts[k] = f
			}
		}
	}
	if s.costCapped(&d, now) {
		if err := store.Save(s.d.Home, &d); err != nil {
			return nil, err
		}
		s.publish(id, "record")
		return nil, nil
	}
	t := &ticker{s: s, ctx: ctx, d: &d, facts: facts, now: now}
	t.run()
	s.publish(id, "record")
	return t.new, nil
}

// reread lists the epic's (or the pick's) children again.
func (s *Service) reread(ctx context.Context, d *store.Dispatch) ([]Child, error) {
	var out []Child
	if d.Epic != nil {
		r, err := s.ResolveEpic(ctx, *d.Epic, false)
		if err != nil {
			return nil, err
		}
		out = r.Children
	}
	byRepo := map[string][]string{}
	var order []string
	for _, k := range append(append([]string{}, d.Issues...), d.Added...) {
		repo, _, _ := strings.Cut(k, "#")
		if _, ok := byRepo[repo]; !ok {
			order = append(order, repo)
		}
		byRepo[repo] = append(byRepo[repo], k)
	}
	for _, repo := range order {
		r, err := s.ResolveIssues(ctx, byRepo[repo], false)
		if err != nil {
			return nil, err
		}
		out = append(out, r.Children...)
	}
	return out, nil
}

// laneCost is the cost and tokens of a lane's sessions.
func (s *Service) laneCost(x *store.Lane) (float64, sessions.Tokens, bool) {
	var cost float64
	var tok sessions.Tokens
	seen := false
	if s.d.Sessions == nil {
		return 0, tok, false
	}
	for _, h := range x.Handles {
		rec, err := s.d.Sessions.Get(h.Session)
		if err != nil {
			continue
		}
		if rec.Cost != nil {
			cost += *rec.Cost
		}
		if rec.Tokens != nil {
			tok.Input += rec.Tokens.Input
			tok.Cached += rec.Tokens.Cached
			tok.Output += rec.Tokens.Output
			seen = true
		}
	}
	return cost, tok, seen
}

// costCapped pauses a running dispatch whose lanes have cost its max_cost; sessions running now
// finish their turn.
func (s *Service) costCapped(d *store.Dispatch, now float64) bool {
	if d.Settings.MaxCost == nil || d.State != store.Running {
		return false
	}
	var spent float64
	for _, x := range d.Lanes {
		c, _, _ := s.laneCost(x)
		spent += c
	}
	if spent < *d.Settings.MaxCost {
		return false
	}
	d.State = store.Paused
	text := fmt.Sprintf("cost cap reached: $%.2f of $%.2f", spent, *d.Settings.MaxCost)
	d.AddEvent("", "paused", text, now)
	s.notify(d, "", "needs_you", text)
	return true
}

// notify sends the board event `dispatch` (W§2.7), or `stalled` for a lane the idle guard let stop.
func (s *Service) notify(d *store.Dispatch, lane, kind, text string) {
	if s.d.Notify == nil {
		return
	}
	who := lane
	if who == "" && d.Epic != nil {
		who = *d.Epic
	}
	if who == "" {
		who = d.Title
	}
	repo, issue := d.Repo(), 0
	if x := d.Lanes[lane]; x != nil {
		repo, issue = x.Repo, x.N
	}
	o, n := splitSlug(repo)
	event := "dispatch"
	if kind == "stalled" {
		event = "stalled"
	}
	s.d.Notify.Notify(event, notify.Note{Repo: repo, Text: who + " " + text,
		Link: &notify.Link{Owner: o, Repo: n, Issue: issue}})
}

// ---- merge ----

func (s *Service) merge(ctx context.Context, repo string, pr int, sha string) (bool, string) {
	if s.d.Merge != nil {
		return s.d.Merge(ctx, repo, pr, sha)
	}
	r := s.d.GH.Run(ctx, []string{"pr", "merge", fmt.Sprint(pr), "-R", repo, "--merge", "--match-head-commit", sha},
		execx.Opts{Timeout: ghTickTimeout})
	if r.Code == 0 {
		return true, ""
	}
	msg := strings.TrimSpace(string(r.Stderr))
	if msg == "" {
		msg = strings.TrimSpace(string(r.Stdout))
	}
	return false, trunc(msg, 300)
}
