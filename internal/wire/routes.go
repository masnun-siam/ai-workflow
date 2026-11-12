package wire

import (
	"context"
	"strings"

	"github.com/masnun-siam/setu/internal/away"
	"github.com/masnun-siam/setu/internal/blubird"
	"github.com/masnun-siam/setu/internal/claude"
	"github.com/masnun-siam/setu/internal/dispatch"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/grind"
	"github.com/masnun-siam/setu/internal/inbox"
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

func (a *App) buildRoutes(disp *dispatch.Service) {
	add := func(r ...[]server.Route) {
		for _, x := range r {
			a.routes = append(a.routes, x...)
		}
	}
	add(
		settings.Routes(settings.Deps{Store: a.Settings}),
		claude.Routes(claude.Deps{Settings: a.Settings}),
		blubird.Routes(blubird.Deps{Manager: a.Blubird}),
		prompts.Routes(prompts.Deps{Registry: a.Prompts}),
		notify.Routes(notify.Deps{Svc: a.Notify}),
		products.Routes(products.Deps{
			Reg: a.Products,
			Merged: func(repo string, n int) (string, bool) {
				for _, m := range a.Poller.Snapshot(repo).Data.Merged {
					if m.N == n {
						return m.Head, true
					}
					for _, c := range m.Closes {
						if c == n {
							return m.Head, true
						}
					}
				}
				return "", false
			},
			VaultPRD: a.Vault.PRDFile,
		}),
		gh.Routes(gh.Deps{
			Client: a.GH,
			Repoll: func(ctx context.Context, slug string) { a.Poller.Poll(ctx, slug, true) },
			OpenChildren: func(slug string, epic int) []int {
				var out []int
				for _, i := range a.Poller.Snapshot(slug).Data.Issues {
					if i.Parent != nil && i.Parent.N == epic && strings.EqualFold(i.Parent.Repo, slug) && i.State != "CLOSED" {
						out = append(out, i.N)
					}
				}
				return out
			},
		}),
		poller.Routes(poller.Deps{Poller: a.Poller, ProductRepos: func(product string) ([]string, bool) {
			p, ok := a.Products.ProductOf(product)
			if !ok {
				return nil, false
			}
			var out []string
			for _, r := range p.Repos {
				if r.Repo != "" {
					out = append(out, r.Repo)
				}
			}
			return out, true
		}}),
		sessions.Routes(sessions.RouteDeps{Manager: a.Sessions}),
		review.Routes(review.RouteDeps{Svc: a.Review}),
		dispatch.Routes(dispatch.RouteDeps{Service: disp}),
		grind.Routes(a.Grind),
		release.Routes(a.Release),
		away.Routes(away.RouteDeps{Service: a.Away}),
		vault.Routes(vault.RouteDeps{Svc: a.Vault}),
		inbox.Routes(a.Inbox),
		views.Routes(a.Views),
	)
}
