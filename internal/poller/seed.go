package poller

import "time"

// Seed installs s as the repo's state without touching GitHub. For tests of consumers
// (see pollertest) and for wiring that restores nothing: the poller never persists.
func (p *Poller) Seed(s Snapshot) {
	p.mu.Lock()
	defer p.mu.Unlock()
	e := p.entryLocked(s.Repo)
	e.data, e.stale, e.err = s.Data, s.Stale, s.Error
	if s.FetchedAt != nil {
		e.fetchedAt = *s.FetchedAt
	} else {
		e.fetchedAt = time.Time{}
	}
	if s.RetryAt != nil {
		e.pausedUntil = *s.RetryAt
	}
	e.dataHash = hashData(s.Data)
}

// FireFresh calls the OnFresh hooks for repo with its current snapshot and the given previous data,
// as a successful poll would. For tests of OnFresh consumers.
func (p *Poller) FireFresh(repo string, prev Data) {
	p.mu.Lock()
	snap := p.snapshotLocked(repo)
	hooks := append([]func(string, Snapshot, Data){}, p.onFresh...)
	p.mu.Unlock()
	for _, fn := range hooks {
		callHook(fn, snap.Repo, snap, prev)
	}
}
