package products

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
)

// Map states of a checkout (Repo.Map).
const (
	MapDocs    = "docs"    // holds .blubird/repos.json
	MapPointer = "pointer" // holds only .blubird/docs-repo
	MapNone    = "none"
)

// mapState says which blubird file the checkout at path holds. Pure file reads.
func mapState(path string) string {
	switch {
	case exists(filepath.Join(path, ".blubird", "repos.json")):
		return MapDocs
	case exists(filepath.Join(path, ".blubird", "docs-repo")):
		return MapPointer
	}
	return MapNone
}

// NeedsMap reports whether repo (a registered slug or an absolute checkout path) has neither a map
// nor a pointer and belongs to no product, so a docs step there must first get the monorepo choice
// (FR-12). A repo it cannot resolve, or one with no slug, never needs one: today's error stays.
func (r *Registry) NeedsMap(ctx context.Context, repo string) (string, bool) {
	path, slug, err := r.Resolve(ctx, repo)
	if err != nil || slug == "" || mapState(path) != MapNone {
		return slug, false
	}
	if _, ok := r.ProductOf(slug); ok {
		return slug, false
	}
	return slug, true
}

// Monorepo makes the registered repo slug its own Documentation Repo: it writes a one-entry
// .blubird/repos.json ("path": ".") and registers the product. It never overwrites a map or
// pointer and never runs git add or commit (FR-13). wrote is false when the identical map was
// already there.
func (r *Registry) Monorepo(ctx context.Context, slug string) (Product, bool, error) {
	key, ok := findKey(r.checkouts(), slug)
	if !ok {
		return Product{}, false, errs.NotFound("%s is not a registered repo", slug)
	}
	top, err := validateRepo(ctx, r.checkouts()[key])
	if err != nil {
		return Product{}, false, err
	}
	origin := originSlug(ctx, top)
	if origin == "" {
		return Product{}, false, errs.Invalid("%s has no GitHub origin: add a remote first", key)
	}
	if p, ok := r.ProductOf(origin); ok && mapState(top) != MapDocs {
		return Product{}, false, errs.Conflict(key+" is already part of product "+p.DocsRepo, nil)
	}
	want := mapEntry{Name: origin[strings.Index(origin, "/")+1:], Role: "docs", Repo: origin, Path: "."}
	wrote, err := r.writeMonorepoMap(top, key, want)
	if err != nil {
		return Product{}, false, err
	}
	p, err := r.Register(ctx, top)
	if err != nil {
		return Product{}, false, err
	}
	if wrote {
		r.setCommitted(p.DocsRepo, false)
		p.MapCommitted = false
	}
	return p, wrote, nil
}

// writeMonorepoMap writes the one-entry map unless a map or pointer is there already; an existing
// map equal to want is accepted without a write.
func (r *Registry) writeMonorepoMap(top, key string, want mapEntry) (bool, error) {
	file := filepath.Join(top, ".blubird", "repos.json")
	taken := errs.Conflict(key+" already has a repo map or docs-repo pointer", nil)
	r.mu.Lock()
	defer r.mu.Unlock()
	if exists(filepath.Join(top, ".blubird", "docs-repo")) {
		return false, taken
	}
	if exists(file) {
		m, err := readMap(top)
		if err != nil || len(m.Entries) != 1 {
			return false, taken
		}
		e := m.Entries[0]
		if e.Name != want.Name || e.Role != want.Role || e.Path != want.Path || !eqFold(e.Repo, want.Repo) {
			return false, taken
		}
		return false, nil
	}
	type entry struct {
		Name string `json:"name"`
		Role string `json:"role"`
		Repo string `json:"repo"`
		Path string `json:"path"`
	}
	data, err := json.MarshalIndent(map[string][]entry{"repos": {entry(want)}}, "", "  ")
	if err != nil {
		return false, err
	}
	// AtomicWrite would create a missing folder 0o700; .blubird is part of the repo
	if err := os.MkdirAll(filepath.Dir(file), 0o755); err != nil {
		return false, err
	}
	if err := home.AtomicWrite(file, append(data, '\n'), 0o644); err != nil {
		return false, err
	}
	return true, nil
}

// mapCommitted reads the cache refreshCommitted fills; a product not cached yet reads as true.
func (r *Registry) mapCommitted(docsSlug string) bool {
	r.commitMu.RLock()
	defer r.commitMu.RUnlock()
	v, ok := r.committed[strings.ToLower(docsSlug)]
	return !ok || v
}

// setCommitted stores v and reports whether the value read by mapCommitted changed.
func (r *Registry) setCommitted(docsSlug string, v bool) bool {
	k := strings.ToLower(docsSlug)
	r.commitMu.Lock()
	defer r.commitMu.Unlock()
	if r.committed == nil {
		r.committed = map[string]bool{}
	}
	old, ok := r.committed[k]
	r.committed[k] = v
	return (!ok || old) != v
}

// refreshCommitted records, for every valid product, whether .blubird/repos.json is tracked at
// its checkout's HEAD (not the index), and tells the UI when that changed (FR-13). Poll tick only.
func (r *Registry) refreshCommitted(ctx context.Context) {
	for _, p := range r.Products() {
		if p.Error != "" || ctx.Err() != nil {
			continue
		}
		ok := git(ctx, p.Path, "cat-file", "-e", "HEAD:.blubird/repos.json").Code == 0
		if r.setCommitted(p.DocsRepo, ok) {
			r.changed("registry", p.DocsRepo)
		}
	}
}
