// Server half of the grind package: the Service that the setu server runs. It keeps the grind
// index (state files plus live sessions), re-enters loops on a timer, starts grinds when a draft PR
// turns ready, scans for finished or paused grinds to notify, and serves the HTTP routes. Files:
// service.go (Deps, Service, loops), index.go (states), tick.go (re-entry), actions.go (start,
// autostart, skip-ci, stop, per-issue switch), notifyscan.go, routes.go. The CLI half (state.go,
// ops.go, ...) does the mechanics inside a grind session.
package grind

import (
	"context"
	"log"
	"regexp"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/jev"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
	"github.com/masnun-siam/setu/internal/settings"
)

const (
	// MaxGrinds is the number of grind sessions the timer lets run at once (W§6.2).
	MaxGrinds = 2
	// TickEvery is the re-entry period, NotifyEvery the notify scan period, ScanEvery the index
	// change check that publishes products{grind}.
	TickEvery   = 60 * time.Second
	NotifyEvery = 30 * time.Second
	ScanEvery   = 10 * time.Second
)

// LaneOwner is what grind needs from dispatch (satisfied by *dispatch.Service). A nil LaneOwner
// means no dispatch exists.
type LaneOwner interface {
	ActiveLane(repo string, issue, pr int) (dispatchID string, ok bool)
	GrindMode(prURL string) (mode string, ok bool)
}

// Sessions is the part of *sessions.Manager the service uses.
type Sessions interface {
	StartSession(ctx context.Context, req sessions.StartRequest) (sessions.Record, error)
	Launch(ctx context.Context, s sessions.Spec) (sessions.Record, error)
	List(f sessions.Filter) []sessions.Record
	SendPrompt(ctx context.Context, id, text string, limit int) (string, error)
	Public(r sessions.Record) sessions.Session
}

// Prompts is the part of *prompts.Registry the service uses.
type Prompts interface {
	BuildIn(step, args, repo string) (prompts.Prompt, error)
}

// Notifier is satisfied by *notify.Service.
type Notifier interface {
	Notify(event string, n notify.Note)
}

// Snapshots is satisfied by *poller.Poller.
type Snapshots interface {
	Snapshot(repo string) poller.Snapshot
}

// Repos is the part of *products.Registry the service uses to find a checkout.
type Repos interface {
	Resolve(ctx context.Context, repo string) (path, slug string, err error)
}

// Deps wires a Service. Home, Settings, Sessions and Prompts are required; the rest may be nil.
// Jev is accepted for symmetry with API §2; the server half does not call it (the CLI half does).
type Deps struct {
	Home     *home.Home
	GH       gh.Client
	Sessions Sessions
	Prompts  Prompts
	Settings *settings.Store
	Jev      *jev.Client
	Poller   Snapshots
	Notify   Notifier
	Products Repos
	Lanes    LaneOwner
	Bus      *events.Bus
	Now      func() time.Time
}

// Service is the server half of the grind.
type Service struct {
	d Deps

	startMu  sync.Mutex // one start at a time, so two triggers cannot both pass the "no loop yet" check
	tickMu   sync.Mutex // ticks never overlap
	notifyMu sync.Mutex
	hashMu   sync.Mutex
	lastHash string
}

// New builds a Service.
func New(d Deps) *Service { return &Service{d: d} }

func (s *Service) now() time.Time {
	if s.d.Now != nil {
		return s.d.Now().UTC()
	}
	return time.Now().UTC()
}

func (s *Service) files() Files { return Files{s.d.Home} }

func (s *Service) warn(format string, a ...any) { log.Printf("grind: "+format, a...) }

// changed tells the UI the grind index moved.
func (s *Service) changed(repo string) {
	if s.d.Bus != nil {
		s.d.Bus.Publish(events.TProducts, map[string]any{"kind": "grind", "repo": repo})
	}
}

// Start runs the loops until ctx ends: the re-entry tick (60 s), the notify scan (30 s, the first
// scan runs now and is silent) and the index change check (10 s). It returns when ctx is done.
func (s *Service) Start(ctx context.Context) {
	s.NotifyScan()
	s.scanChange()
	tick := time.NewTicker(TickEvery)
	nt := time.NewTicker(NotifyEvery)
	sc := time.NewTicker(ScanEvery)
	defer tick.Stop()
	defer nt.Stop()
	defer sc.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-tick.C:
			s.Tick(ctx)
		case <-nt.C:
			s.NotifyScan()
		case <-sc.C:
			s.scanChange()
		}
	}
}

var slugRE = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
