package inbox

import (
	"context"
	"time"

	"github.com/masnun-siam/setu/internal/blubird"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/jev"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/products"
	"github.com/masnun-siam/setu/internal/sessions"
)

// Every dependency is optional: a nil one contributes nothing. The real *sessions.Manager,
// *poller.Poller, *products.Registry, *gh.AuthCache, *blubird.Manager and *jev.Client satisfy their
// interfaces as they are; the packages built in parallel (grind, dispatch, release, away, review)
// are adapted by the wiring, usually with Convert.

// Sessions is satisfied by *sessions.Manager.
type Sessions interface {
	List(f sessions.Filter) []sessions.Record
	Public(r sessions.Record) sessions.Session
}

// Snapshots is satisfied by *poller.Poller.
type Snapshots interface {
	Snapshot(repo string) poller.Snapshot
	MarkViewed(repo string)
	Watched() []string
}

// Products is satisfied by *products.Registry.
type Products interface {
	Products() []products.Product
	Repos() []products.Repo
	PRDs(product string) ([]products.PRD, error)
}

// GHAuth is satisfied by *gh.AuthCache.
type GHAuth interface {
	Get(ctx context.Context) gh.Auth
}

// BlubirdStatus is satisfied by *blubird.Manager.
type BlubirdStatus interface {
	Status() blubird.Status
}

// GrindSettings answers "is grinding on for this issue": the per-issue switch, else the repo's
// auto_grind. settings.Store is adapted with StoreGrind.
type GrindSettings interface {
	GrindOn(slug string, issue int) bool
}

// Grinds lists every grind (grind.Service.Index, adapted).
type Grinds interface {
	Index() []GrindStatus
}

// Dispatches is dispatch.Service, adapted.
type Dispatches interface {
	List() []Dispatch
	Owned(repo string, issue, pr int) bool
}

// AwayState is away.Service, adapted.
type AwayState interface {
	Public() Away
}

// Panels is review.Service, adapted.
type Panels interface {
	List() []Panel
}

// Releases is release.Service, adapted. product "" means every product.
type Releases interface {
	List(product string) []Release
	Repos(product string) []ReleaseRepo
}

// CleanupFlags returns the merge-cleanup flags of a repo by issue number (memory only, set when a
// merged PR is first seen).
type CleanupFlags interface {
	Flags(repo string) map[int]products.CleanupFlags
}

// Jev is satisfied by *jev.Client.
type Jev interface {
	Status() string
	Peek(point, kind, question, text string, options map[string]string, levels []string) *jev.Answer
	Ask(ctx context.Context, point, kind, question, text string, options map[string]string, levels []string) jev.Answer
	Spent() int
}

// Deps wires a Builder.
type Deps struct {
	Sessions  Sessions
	Snapshots Snapshots
	Products  Products
	GH        GHAuth
	Blubird   BlubirdStatus
	Settings  GrindSettings
	Grinds    Grinds
	Dispatch  Dispatches
	Away      AwayState
	Panels    Panels
	Releases  Releases
	Cleanup   CleanupFlags
	Jev       Jev
	Bus       *events.Bus

	// PRDStatus reads the **Status:** of a PRD file by absolute path ("" = unknown). Default reads
	// the file head.
	PRDStatus func(artifact string) string
	Now       func() time.Time
}
