package release

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/products"
	"github.com/masnun-siam/setu/internal/sessions"
)

// Products is the part of products.Registry release reads.
type Products interface {
	Products() []products.Product
	Repos() []products.Repo
}

// Deps wires a Service. Home, Sessions, Prompts, GH and Settings are required.
type Deps struct {
	Home     *home.Home
	Bus      *events.Bus
	Sessions Sessions
	Prompts  Prompts
	GH       gh.Client
	Grind    Grinds
	Settings Settings
	Products Products
	Notify   Notifier
	// Merged is the poller's merged list: the PR merged time when PR n of repo is in it.
	// Optional; without it (or on a miss) release asks `gh pr view`.
	Merged func(repo string, n int) (mergedAt string, ok bool)
	Now    func() time.Time
}

// Service runs the release flow.
type Service struct {
	d Deps

	mu     sync.Mutex // cut (one open per repo) and draft start (once)
	posts  sync.Map   // release id -> struct{} while a post is running in this process
	cache  sync.Map   // repo -> aheadEntry
	viewAt sync.Map   // release id -> time of the last gh pr view
}

// New builds a Service.
func New(d Deps) *Service { return &Service{d: d} }

func (s *Service) now() time.Time {
	if s.d.Now != nil {
		return s.d.Now().UTC()
	}
	return time.Now().UTC()
}

func ts(t time.Time) string { return t.UTC().Format("2006-01-02T15:04:05Z") }

func sp(s string) *string { return &s }

func (s *Service) dir() string               { return s.d.Home.Path("releases") }
func (s *Service) file(id string) string     { return filepath.Join(s.dir(), id+".json") }
func (s *Service) noteFile(id string) string { return filepath.Join(s.dir(), id, "note.md") }

func (s *Service) changed(repo string) {
	if s.d.Bus != nil {
		s.d.Bus.Publish(events.TProducts, map[string]any{"kind": "release", "repo": repo})
	}
}

func newID(t time.Time) string {
	var b [3]byte
	_, _ = rand.Read(b[:])
	return "r-" + t.UTC().Format("20060102T150405Z") + "-" + hex.EncodeToString(b[:])
}

// ---- store ----

func (s *Service) load(id string) (record, error) {
	if !idRE.MatchString(id) {
		return record{}, errs.NotFound("release not found")
	}
	var r record
	if err := home.ReadJSON(s.file(id), &r); err != nil {
		return record{}, err
	}
	if r.ID == "" {
		return record{}, errs.NotFound("release not found")
	}
	return r, nil
}

// mutate is a locked read-modify-write; fn may return an error to abort without writing.
func (s *Service) mutate(id string, fn func(*record) error) (record, error) {
	if _, err := s.load(id); err != nil {
		return record{}, err
	}
	r, err := home.UpdateJSON(s.file(id), func(r *record) error {
		if err := fn(r); err != nil {
			return err
		}
		r.UpdatedAt = ts(s.now())
		return nil
	})
	if err != nil {
		return r, err
	}
	s.changed(r.Repo)
	return r, nil
}

func (s *Service) records() []record {
	ents, _ := os.ReadDir(s.dir())
	var out []record
	for _, e := range ents {
		n := e.Name()
		if e.IsDir() || !strings.HasSuffix(n, ".json") || !idRE.MatchString(strings.TrimSuffix(n, ".json")) {
			continue
		}
		var r record
		if home.ReadJSON(filepath.Join(s.dir(), n), &r) == nil && r.ID != "" {
			out = append(out, r)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].CreatedAt != out[j].CreatedAt {
			return out[i].CreatedAt > out[j].CreatedAt
		}
		return out[i].ID > out[j].ID
	})
	return out
}

func (s *Service) openFor(repo string) (record, bool) {
	for _, r := range s.records() {
		if strings.EqualFold(r.Repo, repo) && open(r.Stage) {
			return r, true
		}
	}
	return record{}, false
}

// ---- cut ----

func (s *Service) branches(repo string, o CutOpts) (head, base string) {
	rs := s.d.Settings.Get().Repo(repo)
	head, base = o.Head, o.Base
	if head == "" {
		head = rs.ReleaseHead
	}
	if base == "" {
		base = rs.ReleaseBase
	}
	if head == "" {
		head = "staging"
	}
	if base == "" {
		base = "master"
	}
	return head, base
}

// Cut starts a release for repo: a `release-pr` session. One open release per repo (409).
func (s *Service) Cut(ctx context.Context, repo string, dryRun bool) (Release, error) {
	return s.CutWith(ctx, repo, CutOpts{DryRun: dryRun})
}

// CutWith is Cut with the partial-release and branch options.
func (s *Service) CutWith(ctx context.Context, repo string, o CutOpts) (Release, error) {
	if !slugRE.MatchString(repo) {
		return Release{}, errs.Invalid("repo must look like owner/name")
	}
	for _, b := range []string{o.Head, o.Base} {
		if b != "" && (!branchRE.MatchString(b) || strings.Contains(b, "..")) {
			return Release{}, errs.Invalid("bad branch name %q", b)
		}
	}
	slug, ok := s.registered(repo)
	if !ok {
		return Release{}, errs.NotFound("%s is not a registered repo", repo)
	}
	head, base := s.branches(slug, o)

	s.mu.Lock()
	defer s.mu.Unlock()
	if r, ok := s.openFor(slug); ok {
		return Release{}, errs.Conflict(fmt.Sprintf("a release is already in flight for %s (%s)", slug, r.Stage),
			map[string]any{"id": r.ID, "href": "#/releases/" + r.ID})
	}
	now := s.now()
	r := record{ID: newID(now), Repo: slug, Head: head, Base: base, Stage: StCut, DryRun: o.DryRun,
		Partial: o.Partial, CreatedAt: ts(now), UpdatedAt: ts(now)}
	if err := os.MkdirAll(filepath.Join(s.dir(), r.ID), 0o755); err != nil {
		return Release{}, err
	}
	if err := home.WriteJSON(s.file(r.ID), r); err != nil {
		return Release{}, err
	}

	args := head + " " + base
	if o.DryRun {
		args = "--dry-run " + args
	}
	p, err := s.d.Prompts.BuildIn("release-pr", args, slug)
	if err != nil {
		s.fail(r.ID, "cannot build the release-pr prompt: "+err.Error())
		return Release{}, err
	}
	spec := sessions.Spec{Prompt: sessions.Prompt(p), Args: args, Cwd: slug, Kind: "release",
		Fields: map[string]any{"release": r.ID}}
	if o.Partial {
		spec.Instructions = []string{"This is a partial release. Follow \"Partial release: holding a theme back\": " +
			"group the PRs into themes, ask with `setu ask` which themes or PRs to hold back, then build the release branch."}
	}
	rec, err := s.d.Sessions.Launch(ctx, spec)
	if err != nil {
		s.fail(r.ID, "release-pr did not start: "+err.Error())
		return Release{}, err
	}
	out, err := s.mutate(r.ID, func(x *record) error { x.CutSess = sp(rec.ID); return nil })
	if err != nil {
		return Release{}, err
	}
	return s.Public(out), nil
}

func (s *Service) fail(id, msg string) {
	_, _ = s.mutate(id, func(r *record) error {
		r.Stage, r.Error = StFailed, sp(msg)
		return nil
	})
}

func (s *Service) registered(repo string) (string, bool) {
	if s.d.Products == nil {
		return repo, true
	}
	for _, r := range s.d.Products.Repos() {
		if strings.EqualFold(r.Slug, repo) {
			return r.Slug, true
		}
	}
	return "", false
}

// ---- read ----

// Get returns one release.
func (s *Service) Get(id string) (Release, error) {
	r, err := s.load(id)
	if err != nil {
		return Release{}, err
	}
	return s.Public(r), nil
}

// List returns the releases of a product's repos (all when product is ""), newest first.
// Finished ones are kept for 30 days.
func (s *Service) List(product string) []Release {
	var keep map[string]bool
	if product != "" {
		keep = map[string]bool{}
		for _, r := range s.productRepos(product) {
			keep[strings.ToLower(r)] = true
		}
	}
	cutoff := s.now().Add(-30 * 24 * time.Hour)
	out := []Release{}
	for _, r := range s.records() {
		if keep != nil && !keep[strings.ToLower(r.Repo)] {
			continue
		}
		if !open(r.Stage) {
			if t, err := time.Parse(time.RFC3339, r.UpdatedAt); err == nil && t.Before(cutoff) {
				continue
			}
		}
		out = append(out, s.Public(r))
	}
	return out
}

func (s *Service) productRepos(product string) []string {
	if s.d.Products == nil {
		return nil
	}
	var out []string
	seen := map[string]bool{}
	for _, p := range s.d.Products.Products() {
		if !strings.EqualFold(p.DocsRepo, product) {
			continue
		}
		for _, r := range p.Repos {
			if r.Repo == "" || strings.EqualFold(r.Role, "docs") || seen[strings.ToLower(r.Repo)] {
				continue
			}
			seen[strings.ToLower(r.Repo)] = true
			out = append(out, r.Repo)
		}
	}
	return out
}

type aheadEntry struct {
	n  *int
	at time.Time
}

const aheadTTL = 2 * time.Minute

// Repos lists the releasable repos of a product (all registered repos when product is "").
func (s *Service) Repos(product string) []ReleaseRepo {
	var slugs []string
	if product != "" {
		slugs = s.productRepos(product)
	} else if s.d.Products != nil {
		for _, r := range s.d.Products.Repos() {
			if !strings.HasPrefix(r.Slug, "local/") {
				slugs = append(slugs, r.Slug)
			}
		}
	}
	recs := s.records()
	out := make([]ReleaseRepo, len(slugs))
	var wg sync.WaitGroup
	for i, slug := range slugs {
		head, base := s.branches(slug, CutOpts{})
		rr := ReleaseRepo{Repo: slug, Name: slug[strings.LastIndex(slug, "/")+1:], Head: head, Base: base, Actions: []Action{}}
		for _, r := range recs {
			if !strings.EqualFold(r.Repo, slug) {
				continue
			}
			if open(r.Stage) && rr.Open == nil {
				rr.Open = sp(r.ID)
			}
			if r.Stage == StDone && r.PR != nil && r.MergedAt != nil && rr.LastRelease == nil {
				rr.LastRelease = &LastRelease{PR: *r.PR, MergedAt: *r.MergedAt}
			}
		}
		rr.Actions = repoActions(rr)
		out[i] = rr
		wg.Add(1)
		go func(i int, slug, head, base string) {
			defer wg.Done()
			n, at := s.ahead(slug, head, base)
			out[i].Ahead = n
			if !at.IsZero() {
				out[i].CheckedAt = sp(ts(at))
			}
		}(i, slug, head, base)
	}
	wg.Wait()
	return out
}

// ahead counts the commits head has over base (GitHub compare), cached for two minutes.
func (s *Service) ahead(slug, head, base string) (*int, time.Time) {
	key := slug + "|" + head + "|" + base
	if v, ok := s.cache.Load(key); ok {
		e := v.(aheadEntry)
		if s.now().Sub(e.at) < aheadTTL {
			return e.n, e.at
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	var v any
	_, err := s.d.GH.JSON(ctx, []string{"api", "repos/" + slug + "/compare/" + base + "..." + head, "--jq", ".ahead_by"}, 20*time.Second, &v)
	var n *int
	if err == nil {
		switch x := v.(type) {
		case float64:
			i := int(x)
			n = &i
		case string:
			var i int
			if _, e := fmt.Sscanf(x, "%d", &i); e == nil {
				n = &i
			}
		}
	}
	e := aheadEntry{n: n, at: s.now()}
	s.cache.Store(key, e)
	return e.n, e.at
}
