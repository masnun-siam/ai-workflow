package poller

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/gh"
)

// Cadence and limits (G§1.3, G§10).
const (
	PollSeconds     = 60 * time.Second
	FastPollSeconds = 15 * time.Second // any open PR with ci pending
	ColdPollSeconds = 600 * time.Second
	FullEvery       = 600 * time.Second
	RateLimitPause  = 600 * time.Second
	LowBudget       = 1000
	ViewWindow      = 120 * time.Second
	TickEvery       = 5 * time.Second
	projectsBackoff = time.Hour
)

var slugRE = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)

// Options configure a Poller. Watched lists the repos to poll; Hot says which are viewed or have a
// live session (nil: all hot); Now is the clock; Tick, when set, runs at the start of every 5 s tick
// (the wiring calls products.Sync there).
type Options struct {
	Watched func() []string
	Hot     func(repo string) bool
	Now     func() time.Time
	Tick    func(ctx context.Context)
}

type entry struct {
	slug   string
	pollMu sync.Mutex // one poll of a repo at a time

	data         Data
	stale        bool
	fetchedAt    time.Time
	err          string
	nextDue      time.Time
	pausedUntil  time.Time
	last         time.Time // last poll attempt
	fullAt       time.Time // last full fetch
	probe        string    // the probe's answer at the last full fetch
	projectsOff  time.Time // do not retry the Projects v2 read before this
	projectsNote string

	dataHash  string // hash of data at the last publish decision
	published bool
	pubStale  bool
}

// Poller polls the watched repos. Create with New, run with Start.
type Poller struct {
	c   gh.Client
	bus *events.Bus
	o   Options

	mu      sync.Mutex
	entries map[string]*entry
	budget  struct {
		remaining int
		known     bool
		resetAt   time.Time
	}
	viewed  map[string]time.Time
	onFresh []func(repo string, s Snapshot, prev Data)
	ctx     context.Context
}

func New(c gh.Client, bus *events.Bus, o Options) *Poller {
	if o.Now == nil {
		o.Now = time.Now
	}
	return &Poller{c: c, bus: bus, o: o, entries: map[string]*entry{}, viewed: map[string]time.Time{}}
}

func (p *Poller) now() time.Time { return p.o.Now() }

// entry returns the repo's state, creating it empty and stale. Caller holds p.mu.
func (p *Poller) entryLocked(repo string) *entry {
	k := strings.ToLower(repo)
	e := p.entries[k]
	if e == nil {
		e = &entry{slug: repo, data: EmptyData(), stale: true}
		p.entries[k] = e
	}
	return e
}

func (p *Poller) entry(repo string) *entry {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.entryLocked(repo)
}

// OnFresh registers fn, called after a poll that left the repo fresh, with the data before the poll.
// A panic in fn is logged and swallowed.
func (p *Poller) OnFresh(fn func(repo string, s Snapshot, prev Data)) {
	p.mu.Lock()
	p.onFresh = append(p.onFresh, fn)
	p.mu.Unlock()
}

// Budget is the token's GraphQL budget from the last response. Remaining is -1 while unknown.
func (p *Poller) Budget() gh.RateLimit {
	p.mu.Lock()
	defer p.mu.Unlock()
	if !p.budget.known {
		return gh.RateLimit{Remaining: -1}
	}
	return gh.RateLimit{Remaining: p.budget.remaining, ResetAt: p.budget.resetAt}
}

func (p *Poller) lowLocked(now time.Time) bool {
	return p.budget.known && p.budget.remaining < LowBudget && now.Before(p.budget.resetAt)
}

// Snapshot is the repo's state from memory; it never waits on GitHub.
func (p *Poller) Snapshot(repo string) Snapshot {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.snapshotLocked(repo)
}

func (p *Poller) snapshotLocked(repo string) Snapshot {
	e := p.entryLocked(repo)
	s := Snapshot{Repo: e.slug, Data: e.data, Stale: e.stale, Error: e.err}
	if !e.fetchedAt.IsZero() {
		t := e.fetchedAt.UTC().Truncate(time.Second)
		s.FetchedAt = &t
	}
	if p.now().Before(e.pausedUntil) {
		t := e.pausedUntil.UTC().Truncate(time.Second)
		s.RetryAt = &t
	}
	return s
}

// due: now >= max(nextDue, pausedUntil, hot ? 0 : last + ColdPollSeconds).
func (p *Poller) due(repo string, hot bool) bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	e := p.entryLocked(repo)
	at := e.nextDue
	if e.pausedUntil.After(at) {
		at = e.pausedUntil
	}
	if !hot && e.last.Add(ColdPollSeconds).After(at) {
		at = e.last.Add(ColdPollSeconds)
	}
	return !p.now().Before(at)
}

// call runs one GraphQL query and records a failure on the entry: a rate limit pauses the repo, any
// other failure marks it stale with the message. soft calls leave the entry alone on a
// non-rate-limit failure and return the error.
func (p *Poller) call(ctx context.Context, e *entry, query string, vars map[string]any, out any, soft bool) (bool, error) {
	rl, _, err := p.c.GraphQL(ctx, query, vars, out)
	if err != nil {
		p.mu.Lock()
		defer p.mu.Unlock()
		if errors.Is(err, gh.ErrRateLimited) {
			now := p.now()
			e.stale, e.err = true, "rate limited"
			if p.lowLocked(now) && p.budget.resetAt.After(now) {
				e.pausedUntil = p.budget.resetAt
			} else {
				e.pausedUntil = now.Add(RateLimitPause)
			}
			log.Printf("poller: rate limit on %s, paused until %s", e.slug, e.pausedUntil.Format(time.RFC3339))
			return false, err
		}
		log.Printf("poller: %s: %v", e.slug, err)
		if !soft {
			msg := trunc(err.Error(), 200)
			if msg == "" {
				msg = "gh failed"
			}
			e.stale, e.err = true, msg
		}
		return false, err
	}
	if !rl.ResetAt.IsZero() {
		p.mu.Lock()
		p.budget.remaining, p.budget.known, p.budget.resetAt = rl.Remaining, true, rl.ResetAt
		p.mu.Unlock()
	}
	return true, nil
}

func trunc(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n])
}

func (p *Poller) fail(e *entry, msg string) {
	p.mu.Lock()
	e.stale, e.err = true, trunc(msg, 200)
	p.mu.Unlock()
}

// moreIssues follows the open-issues cursor (MaxIssuePages pages in all). False when a page failed.
func (p *Poller) moreIssues(ctx context.Context, e *entry, owner, name string, resp *response) bool {
	if resp.Data.Repository == nil || resp.Data.Repository.Issues == nil {
		return true // normalize reports it
	}
	iss := resp.Data.Repository.Issues
	for i := 1; i < MaxIssuePages && iss.PageInfo.HasNextPage; i++ {
		var pg response
		if ok, _ := p.call(ctx, e, issuesPageQuery, map[string]any{"owner": owner, "name": name, "after": iss.PageInfo.EndCursor}, &pg, false); !ok {
			return false
		}
		if pg.Data.Repository == nil || pg.Data.Repository.Issues == nil {
			p.fail(e, "malformed issues page")
			return false
		}
		iss.Nodes = append(iss.Nodes, pg.Data.Repository.Issues.Nodes...)
		iss.PageInfo = pg.Data.Repository.Issues.PageInfo
	}
	return true
}

// readProjects reads the Projects v2 Status of the open issues. ok is false only when the call was
// rate limited (the whole poll then pauses). Any other failure (no scope, no project) leaves the
// statuses derived, says why in note, and is not retried for an hour.
func (p *Poller) readProjects(ctx context.Context, e *entry, owner, name string) (statuses map[int]string, note string, ok bool) {
	p.mu.Lock()
	if p.now().Before(e.projectsOff) {
		note = e.projectsNote
		p.mu.Unlock()
		return nil, note, true
	}
	p.mu.Unlock()
	statuses = map[int]string{}
	after := ""
	for i := 0; i < MaxIssuePages; i++ {
		var pg response
		vars := map[string]any{"owner": owner, "name": name}
		if after != "" {
			vars["after"] = after
		}
		if good, err := p.call(ctx, e, projectsQuery, vars, &pg, true); !good {
			if errors.Is(err, gh.ErrRateLimited) {
				return nil, "", false
			}
			note = "project status unavailable: " + trunc(err.Error(), 160)
			p.mu.Lock()
			e.projectsOff, e.projectsNote = p.now().Add(projectsBackoff), note
			p.mu.Unlock()
			return nil, note, true
		}
		if pg.Data.Repository == nil || pg.Data.Repository.Issues == nil {
			break
		}
		for _, is := range pg.Data.Repository.Issues.list() {
			for _, it := range is.ProjectItems.list() {
				if it.FieldValueByName != nil && it.FieldValueByName.Name != "" {
					if _, seen := statuses[is.Number]; !seen || CanonicalStatus(it.FieldValueByName.Name) != "" && CanonicalStatus(statuses[is.Number]) == "" {
						statuses[is.Number] = it.FieldValueByName.Name
					}
				}
			}
		}
		if !pg.Data.Repository.Issues.PageInfo.HasNextPage {
			break
		}
		after = pg.Data.Repository.Issues.PageInfo.EndCursor
	}
	p.mu.Lock()
	e.projectsNote = ""
	p.mu.Unlock()
	return statuses, "", true
}

func hashData(d Data) string {
	b, _ := json.Marshal(d)
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

// Poll runs the probe, then the full query when needed (nothing while rate-limit paused) and
// returns the snapshot. full forces the full query (Refresh, after a write). Polls of one repo
// are serialised.
func (p *Poller) Poll(ctx context.Context, repo string, full bool) Snapshot {
	e := p.entry(repo)
	e.pollMu.Lock()
	defer e.pollMu.Unlock()
	owner, name, _ := strings.Cut(e.slug, "/")

	p.mu.Lock()
	now := p.now()
	if now.Before(e.pausedUntil) {
		s := p.snapshotLocked(repo)
		p.mu.Unlock()
		return s
	}
	e.last = now
	prev := e.data
	p.mu.Unlock()

	vars := map[string]any{"owner": owner, "name": name}
	fresh, dataChanged := false, false
	var probe struct {
		Data struct {
			Repository any `json:"repository"`
		} `json:"data"`
	}
	if ok, _ := p.call(ctx, e, probeQuery, vars, &probe, false); ok {
		ab, _ := json.Marshal(probe.Data.Repository)
		answer := string(ab)
		p.mu.Lock()
		full = full || answer != e.probe || p.now().Sub(e.fullAt) >= FullEvery
		p.mu.Unlock()
		if !full {
			fresh = true // nothing changed: the data in memory is current
		} else {
			var resp response
			ok, _ := p.call(ctx, e, fullQuery, vars, &resp, false)
			if ok {
				ok = p.moreIssues(ctx, e, owner, name, &resp)
			}
			var statuses map[int]string
			var note string
			if ok {
				statuses, note, ok = p.readProjects(ctx, e, owner, name)
			}
			if ok {
				d, err := normalize(e.slug, &resp, statuses, p.now())
				if err != nil {
					log.Printf("poller: %s: %v", e.slug, err)
					p.fail(e, err.Error())
				} else {
					d.ProjectsNote = note
					h := hashData(d)
					p.mu.Lock()
					dataChanged = h != e.dataHash
					e.data, e.dataHash, e.fullAt, e.probe = d, h, p.now(), answer
					p.mu.Unlock()
					fresh = true
				}
			}
		}
	}

	p.mu.Lock()
	now = p.now()
	if fresh {
		e.stale, e.fetchedAt, e.err = false, now, ""
		wait := PollSeconds
		if pendingCI(e.data) {
			wait = FastPollSeconds
		}
		if p.lowLocked(now) && wait < ColdPollSeconds {
			wait = ColdPollSeconds
		}
		e.nextDue = now.Add(wait)
	} else if !now.Before(e.pausedUntil) {
		e.nextDue = now.Add(PollSeconds)
	}
	snap := p.snapshotLocked(repo)
	publish := dataChanged || !e.published || e.pubStale != e.stale
	e.published, e.pubStale = true, e.stale
	hooks := append([]func(string, Snapshot, Data){}, p.onFresh...)
	p.mu.Unlock()

	if publish && p.bus != nil {
		p.bus.Publish(events.TProducts, map[string]any{"kind": "snapshot", "repo": e.slug})
	}
	if fresh {
		for _, fn := range hooks {
			callHook(fn, e.slug, snap, prev)
		}
	}
	return snap
}

func callHook(fn func(string, Snapshot, Data), repo string, s Snapshot, prev Data) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("poller: on_fresh %s: %v", repo, r)
		}
	}()
	fn(repo, s, prev)
}

func pendingCI(d Data) bool {
	for _, is := range d.Issues {
		for _, pr := range is.PRs {
			if pr.State == "OPEN" && pr.CI == "pending" {
				return true
			}
		}
	}
	for _, pr := range d.OpenPRs {
		if pr.CI == "pending" {
			return true
		}
	}
	return false
}

// Watched is the deduplicated list of pollable repos (owner/name, not local/*).
func (p *Poller) Watched() []string {
	if p.o.Watched == nil {
		return nil
	}
	seen := map[string]bool{}
	var out []string
	for _, r := range p.o.Watched() {
		k := strings.ToLower(r)
		if seen[k] || !slugRE.MatchString(r) || strings.HasPrefix(k, "local/") {
			continue
		}
		seen[k] = true
		out = append(out, r)
	}
	return out
}

func (p *Poller) hot(repo string) bool {
	if p.o.Hot == nil {
		return true
	}
	if p.o.Hot(repo) {
		return true
	}
	return p.viewedRecently(repo)
}

func (p *Poller) viewedRecently(repo string) bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	now := p.now()
	for _, k := range []string{strings.ToLower(repo), "*"} {
		if t, ok := p.viewed[k]; ok && now.Sub(t) < ViewWindow {
			return true
		}
	}
	return false
}

// MarkViewed says a UI is looking at repo ("*": every watched repo) for the next ViewWindow. The
// first view of a repo that was not hot polls it at once, in the background.
func (p *Poller) MarkViewed(repo string) {
	targets := []string{repo}
	if repo == "*" {
		targets = p.Watched()
	}
	var cold []string
	for _, r := range targets {
		if !p.hot(r) {
			cold = append(cold, r)
		}
	}
	p.mu.Lock()
	p.viewed[strings.ToLower(repo)] = p.now()
	ctx := p.ctx
	p.mu.Unlock()
	if ctx == nil {
		return
	}
	for _, r := range cold {
		if slugRE.MatchString(r) && p.due(r, true) {
			go p.Poll(ctx, r, false)
		}
	}
}

// Start runs the 5 s tick until ctx ends; it returns at once. A panic in a tick is logged.
func (p *Poller) Start(ctx context.Context) {
	p.mu.Lock()
	p.ctx = ctx
	p.mu.Unlock()
	go func() {
		t := time.NewTicker(TickEvery)
		defer t.Stop()
		for {
			p.safeTick(ctx)
			select {
			case <-ctx.Done():
				return
			case <-t.C:
			}
		}
	}()
}

func (p *Poller) safeTick(ctx context.Context) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("poller: tick: %v", r)
		}
	}()
	p.tick(ctx)
}

func (p *Poller) tick(ctx context.Context) {
	if p.o.Tick != nil {
		p.o.Tick(ctx)
	}
	for _, repo := range p.Watched() {
		if ctx.Err() != nil {
			return
		}
		if p.due(repo, p.hot(repo)) {
			p.Poll(ctx, repo, false)
		}
	}
}

// String helps in test failures.
func (s Snapshot) String() string {
	return fmt.Sprintf("snapshot{%s stale=%v err=%q issues=%d}", s.Repo, s.Stale, s.Error, len(s.Data.Issues))
}
