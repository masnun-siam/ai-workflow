package wire

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/away"
	"github.com/masnun-siam/setu/internal/dispatch"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/grind"
	"github.com/masnun-siam/setu/internal/inbox"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/products"
	"github.com/masnun-siam/setu/internal/release"
	"github.com/masnun-siam/setu/internal/review"
	"github.com/masnun-siam/setu/internal/sessions"
)

// relGrinds adapts *grind.Service to release.Grinds.
type relGrinds struct{ g *grind.Service }

func (r relGrinds) Get(repo string, pr int) (release.GrindStatus, bool) {
	s, ok := r.g.Get(repo, pr)
	if !ok {
		return release.GrindStatus{}, false
	}
	return convert[release.GrindStatus](s), true
}

func (r relGrinds) StartGrind(ctx context.Context, repo string, pr int, by string) (sessions.Record, error) {
	return r.g.StartGrind(ctx, repo, pr, by)
}

// ---- inbox / views mirrors ----

type inboxGrinds struct{ g *grind.Service }

func (i inboxGrinds) Index() []inbox.GrindStatus { return convertList[inbox.GrindStatus](i.g.Index()) }

type inboxDispatch struct{ d *dispatch.Service }

func (i inboxDispatch) List() []inbox.Dispatch {
	var out []inbox.Dispatch
	for _, d := range i.d.List() {
		out = append(out, convert[inbox.Dispatch](i.d.Public(d, false)))
	}
	return out
}
func (i inboxDispatch) Owned(repo string, issue, pr int) bool { return i.d.Owned(repo, issue, pr) }

type viewDispatch struct {
	inboxDispatch
	d *dispatch.Service
}

func (v viewDispatch) Coordinators() []inbox.Coordinator {
	return convertList[inbox.Coordinator](v.d.Coordinators())
}

type inboxAway struct{ a *away.Service }

func (i inboxAway) Public() inbox.Away { return convert[inbox.Away](i.a.Public()) }

type inboxPanels struct{ r *review.Service }

func (i inboxPanels) List() []inbox.Panel { return convertList[inbox.Panel](i.r.List()) }

type inboxReleases struct{ r *release.Service }

func (i inboxReleases) List(product string) []inbox.Release {
	return convertList[inbox.Release](i.r.List(product))
}
func (i inboxReleases) Repos(product string) []inbox.ReleaseRepo {
	return convertList[inbox.ReleaseRepo](i.r.Repos(product))
}

// ---- cleanup flags ----

// cleanup remembers, per repo and issue, the loose work a merged PR's worktree still holds. It is
// computed when the poller sees a PR merged (and again at each fresh poll for flagged issues), so
// the inbox never runs git.
type cleanup struct {
	reg   *products.Registry
	mu    sync.Mutex
	flags map[string]map[int]products.CleanupFlags // repo (lower) -> issue
	seen  map[string]bool                          // repo#pr@sha already evaluated
}

func newCleanup(reg *products.Registry) *cleanup {
	return &cleanup{reg: reg, flags: map[string]map[int]products.CleanupFlags{}, seen: map[string]bool{}}
}

func (c *cleanup) Flags(repo string) map[int]products.CleanupFlags {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := map[int]products.CleanupFlags{}
	for n, f := range c.flags[strings.ToLower(repo)] {
		out[n] = f
	}
	return out
}

func (c *cleanup) onFresh(repo string, s poller.Snapshot, _ poller.Data) {
	path, _, err := c.reg.Resolve(context.Background(), repo)
	if err != nil || path == "" {
		return
	}
	key := strings.ToLower(repo)
	for _, m := range s.Data.Merged {
		k := fmt.Sprintf("%s#%d@%s", key, m.N, m.SHA)
		c.mu.Lock()
		done := c.seen[k]
		c.seen[k] = true
		c.mu.Unlock()
		if done {
			continue
		}
		for _, n := range m.Closes {
			if f := c.reg.CleanupCheck(path, n, m.Head); f != nil {
				c.mu.Lock()
				if c.flags[key] == nil {
					c.flags[key] = map[int]products.CleanupFlags{}
				}
				c.flags[key][n] = *f
				c.mu.Unlock()
			}
		}
	}
	// Re-check the flagged ones: a cleanup clears its flag.
	c.mu.Lock()
	cur := map[int]bool{}
	for n := range c.flags[key] {
		cur[n] = true
	}
	c.mu.Unlock()
	for n := range cur {
		head := ""
		for _, m := range s.Data.Merged {
			for _, x := range m.Closes {
				if x == n {
					head = m.Head
				}
			}
		}
		if f := c.reg.CleanupCheck(path, n, head); f == nil {
			c.mu.Lock()
			delete(c.flags[key], n)
			c.mu.Unlock()
		}
	}
}

// ---- release prs_waiting ----

// newWaiting counts the merged PRs between base and head from the GitHub compare commits (merge
// commits "Merge pull request #n" and squash commits ending "(#n)"), cached for two minutes.
func newWaiting(c gh.Client) func(slug, head, base string) *int {
	type entry struct {
		n  *int
		at time.Time
	}
	var mu sync.Mutex
	cache := map[string]entry{}
	return func(slug, head, base string) *int {
		k := slug + "|" + head + "|" + base
		mu.Lock()
		if e, ok := cache[k]; ok && time.Since(e.at) < 2*time.Minute {
			mu.Unlock()
			return e.n
		}
		mu.Unlock()
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		var v any
		_, err := c.JSON(ctx, []string{"api", "repos/" + slug + "/compare/" + base + "..." + head, "--jq",
			`[.commits[] | select(.commit.message | test("^Merge pull request #|\\(#[0-9]+\\)(\\n|$)"))] | length`}, 20*time.Second, &v)
		var n *int
		if err == nil {
			if f, ok := v.(float64); ok {
				i := int(f)
				n = &i
			}
		}
		mu.Lock()
		cache[k] = entry{n: n, at: time.Now()}
		mu.Unlock()
		return n
	}
}
