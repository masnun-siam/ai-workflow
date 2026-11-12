package wire

import (
	"context"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/away"
	"github.com/masnun-siam/setu/internal/blubird"
	"github.com/masnun-siam/setu/internal/claude"
	"github.com/masnun-siam/setu/internal/dispatch"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/grind"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/inbox"
	"github.com/masnun-siam/setu/internal/jev"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/products"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/release"
	"github.com/masnun-siam/setu/internal/review"
	"github.com/masnun-siam/setu/internal/server"
	"github.com/masnun-siam/setu/internal/sessions"
	"github.com/masnun-siam/setu/internal/settings"
	"github.com/masnun-siam/setu/internal/vault"
	"github.com/masnun-siam/setu/internal/views"
)

// App is the set of built services.
type App struct {
	Home     *home.Home
	Bus      *events.Bus
	Settings *settings.Store
	Blubird  *blubird.Manager
	Prompts  *prompts.Registry
	GH       gh.Client
	Auth     *gh.AuthCache
	Products *products.Registry
	Poller   *poller.Poller
	Notify   *notify.Service
	Jev      *jev.Client
	Usage    *claude.Usage
	Sessions *sessions.Manager
	Review   *review.Service
	Dispatch *dispatch.Service
	Grind    *grind.Service
	Release  *release.Service
	Away     *away.Service
	Vault    *vault.Service
	Inbox    *inbox.Builder
	Views    *views.Service

	routes  []server.Route
	bootID  func() string
	version string
}

// SetBootID gives /api/status the server's boot id (the server is built after the routes).
func (a *App) SetBootID(f func() string) { a.bootID = f }

// Routes are every package's routes.
func (a *App) Routes() []server.Route { return a.routes }

// GrindPlan is the dispatch view of the grind resolver (W§6.4).
func GrindPlan(h *home.Home, st *settings.Store, repoPaths func() map[string]string) func(repo string) dispatch.GrindPlan {
	return func(repo string) dispatch.GrindPlan {
		r := grind.Resolve(st.Get(), grind.LoadChannels(h), repoPaths(), repo)
		var p dispatch.GrindPlan
		if r.Path != nil {
			p.Path = *r.Path
		}
		if r.Skip != nil {
			p.Skip = *r.Skip
		}
		if r.Channel != nil {
			p.Channel = *r.Channel
		}
		return p
	}
}

func checkoutsOf(reg *products.Registry) func() map[string]string {
	return func() map[string]string {
		m := map[string]string{}
		for _, r := range reg.Repos() {
			m[r.Slug] = r.Path
		}
		return m
	}
}

// SetupCLI points the verbs that run without a server at the same adapters.
func SetupCLI() {
	dispatch.CLIGrind = func(h *home.Home) func(repo string) dispatch.GrindPlan {
		st := settings.Open(h, nil)
		reg := products.New(h, nil, nil)
		return GrindPlan(h, st, checkoutsOf(reg))
	}
}

// Build constructs the services in the order of API.md §1.3 (up to, not including, Start).
func Build(ctx context.Context, h *home.Home, bus *events.Bus, version, binDir string) (*App, error) {
	a := &App{Home: h, Bus: bus, version: version}
	a.Settings = settings.Open(h, bus)
	a.Blubird = blubird.New(h, bus)
	reg, err := prompts.Load(h, version, a.Blubird)
	if err != nil {
		return nil, fmt.Errorf("prompts: %w", err)
	}
	a.Prompts = reg
	a.GH = gh.New()
	a.Auth = gh.NewAuth(a.GH)
	a.Products = products.New(h, a.GH, bus)
	a.Notify = notify.New(h, a.Settings, bus)
	a.Jev = jev.New(h, func() bool { return a.Settings.Get().UseJev })

	// Late-bound services (the construction order has cycles through closures only).
	var (
		views_  *views.Service
		disp    *dispatch.Service
		revSvc  *review.Service
		grindSv *grind.Service
	)
	uiPresent := func() bool {
		return bus.Subscribers() > 0 || (views_ != nil && views_.UIPresent())
	}

	a.Usage = claude.NewUsage(a.Settings, bus, uiPresent)

	a.Poller = poller.New(a.GH, bus, poller.Options{
		Watched: func() []string {
			seen := map[string]bool{}
			var out []string
			add := func(list []string) {
				for _, s := range list {
					if k := strings.ToLower(s); !seen[k] {
						seen[k] = true
						out = append(out, s)
					}
				}
			}
			add(a.Products.WatchedRepos())
			if disp != nil {
				add(disp.Repos())
			}
			return out
		},
		Hot: func(repo string) bool {
			if disp != nil {
				for _, r := range disp.Repos() {
					if strings.EqualFold(r, repo) {
						return true
					}
				}
			}
			return false
		},
		Tick: a.Products.Sync,
	})

	// ---- sessions ----
	guard := func(_ context.Context, req sessions.StartRequest, step sessions.Step, slug string, issue int) error {
		if disp != nil && req.Guard && issue > 0 && (step.ID == "implement-issue" || step.ID == "small-change") {
			if id, ok := disp.ActiveLane(slug, issue, 0); ok {
				return errs.Conflict("issue #"+fmt.Sprint(issue)+" is owned by dispatch "+id, map[string]any{"dispatch": id})
			}
		}
		return nil
	}
	a.Sessions = sessions.New(sessions.Deps{
		Home: h, Bus: bus, Settings: sessSettings{a.Settings}, Claude: sessClaude{}, Prompts: sessPrompts{reg},
		Repos: a.Products, Notify: sessNotifier{a.Notify}, Guards: []sessions.StartGuard{guard}, BinDir: binDir,
		Title: func(slug string, issue int) string { return a.titleOf(slug, issue) },
		PanelState: func(id string) string {
			if revSvc == nil {
				return ""
			}
			return revSvc.State(id)
		},
		AfterStart: func(ctx context.Context, rec sessions.Record, req sessions.StartRequest) error {
			return a.afterStart(ctx, revSvc, rec, req)
		},
	})

	// ---- review ----
	revSvc = review.New(review.Deps{Home: h, Bus: bus, Sessions: a.Sessions, Prompts: reg, Notify: a.Notify})
	a.Review = revSvc

	// ---- dispatch ----
	disp = dispatch.New(dispatch.Deps{
		Home: h, GH: a.GH, Sessions: a.Sessions, Prompts: reg, Snapshots: a.Poller, Accounts: a.Settings,
		Notify: a.Notify, Bus: bus, Jev: a.Jev,
		Grind:    GrindPlan(h, a.Settings, checkoutsOf(a.Products)),
		Login:    func(ctx context.Context) string { return a.Auth.Get(ctx).Login },
		SkillDir: a.Blubird.SkillDir,
	})
	a.Dispatch = disp

	// ---- grind ----
	grindSv = grind.New(grind.Deps{Home: h, GH: a.GH, Sessions: a.Sessions, Prompts: reg, Settings: a.Settings,
		Jev: a.Jev, Poller: a.Poller, Notify: a.Notify, Products: a.Products, Lanes: disp, Bus: bus})
	a.Grind = grindSv
	a.Poller.OnFresh(grindSv.OnFresh)

	// ---- cleanup flags (memory only, set when a merged PR is first seen) ----
	cf := newCleanup(a.Products)
	a.Poller.OnFresh(cf.onFresh)

	// ---- release ----
	a.Release = release.New(release.Deps{
		Home: h, Bus: bus, Sessions: a.Sessions, Prompts: reg, GH: a.GH,
		Grind: relGrinds{grindSv}, Settings: a.Settings, Products: a.Products, Notify: a.Notify,
		Merged: func(repo string, n int) (string, bool) {
			for _, m := range a.Poller.Snapshot(repo).Data.Merged {
				if m.N == n {
					return m.MergedAt, true
				}
			}
			return "", false
		},
		PRsWaiting: newWaiting(a.GH),
	})

	// ---- away ----
	a.Away = away.New(away.Deps{Home: h, Bus: bus, Sessions: a.Sessions, Risk: a.Jev, Agents: reg, Notify: a.Notify,
		Lanes: lanes{disp}})
	a.Notify.SetAway(a.Away.Active)

	// ---- vault ----
	a.Vault = vault.New(vault.Deps{Settings: vault.StoreSettings{St: a.Settings}})

	// ---- inbox, views ----
	a.Inbox = inbox.New(inbox.Deps{
		Sessions: a.Sessions, Snapshots: a.Poller, Products: a.Products, GH: a.Auth, Blubird: a.Blubird,
		Settings: inbox.StoreGrind{Store: a.Settings}, Grinds: inboxGrinds{grindSv},
		Dispatch: inboxDispatch{disp}, Away: inboxAway{a.Away}, Panels: inboxPanels{revSvc},
		Releases: inboxReleases{a.Release}, Cleanup: cf, Jev: a.Jev, Bus: bus,
	})
	views_ = views.New(views.Deps{
		Inbox: a.Inbox, Sessions: a.Sessions, Snapshots: a.Poller, Products: a.Products, Prompts: reg,
		Grinds: inboxGrinds{grindSv}, Dispatch: viewDispatch{inboxDispatch{disp}, disp},
		Releases: inboxReleases{a.Release}, Accounts: a.Settings, Usage: a.Usage, Blubird: a.Blubird, GH: a.Auth,
		Away: inboxAway{a.Away}, Poller: a.Poller, Home: h, Version: version,
		BootID:      func() string { return a.bootID() },
		NoteChannel: func() string { return a.Settings.Get().ReleaseNote.ChannelName },
	})
	a.Views = views_
	a.bootID = func() string { return "" }

	a.buildRoutes(disp)
	return a, nil
}

// Start runs the loops (API.md §1.3). Sessions are reconciled first.
func (a *App) Start(ctx context.Context) {
	if err := a.Sessions.Reconcile(ctx); err != nil {
		log.Printf("sessions reconcile: %v", err)
	}
	a.Jev.Start(ctx)
	a.Usage.Start(ctx)
	a.Poller.Start(ctx)
	a.Sessions.Start(ctx)
	a.Review.Start(ctx)
	a.Dispatch.Start(ctx)
	go func() { // grind.Start blocks until ctx ends (unlike the other Start methods)
		defer func() {
			if p := recover(); p != nil {
				log.Printf("grind loop panic: %v", p)
			}
		}()
		a.Grind.Start(ctx)
	}()
	a.Release.Start(ctx)
	a.Away.Start(ctx)
	a.Inbox.Start(ctx)
	go a.releaseAutoGrind(ctx)
}

// titleOf returns an issue or PR title from the poller snapshots.
func (a *App) titleOf(slug string, n int) string {
	s := a.Poller.Snapshot(slug).Data
	for _, i := range s.Issues {
		if i.N == n {
			return i.Title
		}
	}
	for _, p := range s.OpenPRs {
		if p.N == n {
			return p.Title
		}
	}
	for _, m := range s.Merged {
		if m.N == n {
			return m.Title
		}
	}
	return ""
}

// afterStart opens a peer-review panel for a session started with lenses when its args name an
// existing absolute file (the artifact). Otherwise the start stands without a panel.
func (a *App) afterStart(ctx context.Context, r *review.Service, rec sessions.Record, req sessions.StartRequest) error {
	var artifact string
	for _, f := range strings.Fields(req.Args) {
		if filepath.IsAbs(f) {
			if fi, err := os.Stat(f); err == nil && fi.Mode().IsRegular() {
				artifact = f
				break
			}
		}
	}
	if artifact == "" || r == nil {
		return nil
	}
	repo := req.Repo
	if repo == "" {
		repo = filepath.Dir(artifact)
	}
	if _, err := r.Create(ctx, review.CreatePanel{Repo: repo, Artifact: artifact, Lenses: req.Lenses, RootSession: rec.ID, AfterRoot: true}); err != nil {
		log.Printf("review: panel for %s: %v", rec.ID, err)
	}
	return nil
}

// releaseAutoGrind starts the grind of a freshly cut release PR once (the approved flow is
// cut -> grind automatically). A grind that already runs, or ended, is left alone.
func (a *App) releaseAutoGrind(ctx context.Context) {
	started := map[string]bool{}
	var mu sync.Mutex
	t := time.NewTicker(30 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
		func() {
			defer func() {
				if p := recover(); p != nil {
					log.Printf("release autogrind: %v", p)
				}
			}()
			for _, r := range a.Release.List("") {
				if r.Stage != "grind" || r.PR == nil || r.DryRun {
					continue
				}
				mu.Lock()
				done := started[r.ID]
				started[r.ID] = true
				mu.Unlock()
				if done {
					continue
				}
				if g, ok := a.Grind.Get(r.Repo, *r.PR); ok && g.State != "idle" {
					continue
				}
				if _, err := a.Release.Grind(ctx, r.ID); err != nil {
					log.Printf("release %s: grind: %v", r.ID, err)
				}
			}
		}()
	}
}
