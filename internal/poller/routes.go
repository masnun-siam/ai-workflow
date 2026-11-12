package poller

import (
	"context"
	"net/http"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
)

// Deps for Routes. ProductRepos lists the repos (slugs) of a product by its docs repo slug, ok
// false when the product is unknown.
type Deps struct {
	Poller       *Poller
	ProductRepos func(product string) (repos []string, ok bool)
}

// Routes: POST /api/refresh {repo?, product?} starts a full poll in the background (202). With
// neither, every watched repo is refreshed.
func Routes(d Deps) []server.Route {
	return []server.Route{{Pattern: "POST /api/refresh", Handler: server.Handle(func(r *http.Request) (int, any, error) {
		var body struct {
			Repo    string `json:"repo"`
			Product string `json:"product"`
		}
		if err := server.Decode(r, &body); err != nil {
			return 0, nil, err
		}
		watched := d.Poller.Watched()
		var targets []string
		switch {
		case body.Repo != "":
			for _, w := range watched {
				if strings.EqualFold(w, body.Repo) {
					targets = []string{w}
				}
			}
			if targets == nil {
				return 0, nil, errs.Invalid("%s is not watched", body.Repo)
			}
		case body.Product != "":
			if d.ProductRepos == nil {
				return 0, nil, errs.Invalid("unknown product")
			}
			repos, ok := d.ProductRepos(body.Product)
			if !ok {
				return 0, nil, errs.Invalid("unknown product")
			}
			for _, rp := range repos {
				for _, w := range watched {
					if strings.EqualFold(w, rp) {
						targets = append(targets, w)
					}
				}
			}
		default:
			targets = watched
		}
		d.Poller.RefreshAsync(targets)
		return http.StatusAccepted, map[string]any{"ok": true}, nil
	})}}
}

// RefreshAsync runs a full poll of each repo, one after the other, in the background.
func (p *Poller) RefreshAsync(repos []string) {
	if len(repos) == 0 {
		return
	}
	p.mu.Lock()
	ctx := p.ctx
	p.mu.Unlock()
	if ctx == nil {
		ctx = context.Background()
	}
	go func() {
		for _, r := range repos {
			if ctx.Err() != nil {
				return
			}
			p.Poll(ctx, r, true)
		}
	}()
}
