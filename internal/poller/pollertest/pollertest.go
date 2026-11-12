// Package pollertest builds a real *poller.Poller with fixed snapshots, for tests of packages that
// read the poller (inbox, views, grind, dispatch) without GitHub.
package pollertest

import (
	"time"

	"github.com/masnun-siam/setu/internal/gh/ghtest"
	"github.com/masnun-siam/setu/internal/poller"
)

// New returns a poller holding the given snapshots. Its gh client answers every call with exit 99,
// so a stray Poll marks the repo stale instead of reaching the network.
func New(snaps ...poller.Snapshot) *poller.Poller {
	p := poller.New(ghtest.New(), nil, poller.Options{})
	for _, s := range snaps {
		p.Seed(s)
	}
	return p
}

// Fresh is a fresh snapshot of repo holding d, fetched now.
func Fresh(repo string, d poller.Data) poller.Snapshot {
	t := time.Now().UTC().Truncate(time.Second)
	return poller.Snapshot{Repo: repo, Data: d, FetchedAt: &t}
}

// Stale is a stale snapshot of repo (never fetched) holding d.
func Stale(repo string, d poller.Data) poller.Snapshot {
	return poller.Snapshot{Repo: repo, Data: d, Stale: true}
}
