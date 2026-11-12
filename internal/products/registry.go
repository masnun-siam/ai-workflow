// Package products is the repo registry (checkouts.json), the product registry (products.json)
// and blubird's product model: a Documentation Repo (docs/prds/<module>/<feature>.md, epics,
// .blubird/repos.json) plus the code repos its map lists (each with .blubird/docs-repo). A
// monorepo is one repo whose map has a "." entry.
package products

import (
	"context"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/home"
)

// GH is the GitHub client handed in by the wiring. products shells out to gh only for Check, so
// it needs no methods from it (see DECISIONS.md).
type GH interface{}

// Repo is one registered checkout. Product is the docs repo slug of its product, or nil.
type Repo struct {
	Slug    string  `json:"slug"`
	Path    string  `json:"path"`
	Product *string `json:"product"`
}

type ScanResult struct {
	Added      []Repo `json:"added"`
	Duplicates []Repo `json:"duplicates"`
	Repos      []Repo `json:"repos"`
}

type Registry struct {
	h   *home.Home
	gh  GH
	bus *events.Bus
	mu  sync.Mutex // serialises registry mutations inside this process (files are also flocked)
}

func New(h *home.Home, c GH, bus *events.Bus) *Registry {
	return &Registry{h: h, gh: c, bus: bus}
}

func (r *Registry) checkoutsFile() string { return r.h.Path("checkouts.json") }
func (r *Registry) productsFile() string  { return r.h.Path("products.json") }

func (r *Registry) changed(kind, repo string) {
	if r.bus == nil {
		return
	}
	d := map[string]any{"kind": kind}
	if repo != "" {
		d["repo"] = repo
	}
	r.bus.Publish(events.TProducts, d)
}

// readStrings reads a {key: "string"} object; other value types are skipped.
func readStrings(path string) map[string]string {
	var raw map[string]any
	_ = home.ReadJSON(path, &raw)
	out := make(map[string]string, len(raw))
	for k, v := range raw {
		if s, ok := v.(string); ok && s != "" {
			out[k] = s
		}
	}
	return out
}

// updateStrings is a locked read-modify-write that keeps unknown (non-string) values untouched.
func updateStrings(path string, fn func(m map[string]any)) error {
	_, err := home.UpdateJSON(path, func(m *map[string]any) error {
		if *m == nil {
			*m = map[string]any{}
		}
		fn(*m)
		return nil
	})
	return err
}

func (r *Registry) checkouts() map[string]string { return readStrings(r.checkoutsFile()) }

func (r *Registry) setCheckouts(set map[string]string) error {
	if len(set) == 0 {
		return nil
	}
	return updateStrings(r.checkoutsFile(), func(m map[string]any) {
		for slug, path := range set {
			for k := range m {
				if k != slug && eqFold(k, slug) {
					delete(m, k)
				}
			}
			m[slug] = path
		}
	})
}

// promoteLocal renames local/<name> checkouts that now have a GitHub origin to owner/name.
func (r *Registry) promoteLocal(ctx context.Context) {
	co := r.checkouts()
	var local []string
	for k := range co {
		if strings.HasPrefix(k, "local/") {
			local = append(local, k)
		}
	}
	if len(local) == 0 {
		return
	}
	sort.Strings(local)
	renames := map[string]string{}
	for _, k := range local {
		p := co[k]
		if !isDir(p) {
			continue
		}
		slug := originSlug(ctx, p)
		if slug == "" {
			continue
		}
		if _, taken := findKey(co, slug); taken {
			continue
		}
		renames[k] = slug
		co[slug] = p
	}
	if len(renames) == 0 {
		return
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	_ = updateStrings(r.checkoutsFile(), func(m map[string]any) {
		for old, slug := range renames {
			v, ok := m[old]
			if !ok {
				continue
			}
			taken := false
			for k := range m {
				if eqFold(k, slug) {
					taken = true
				}
			}
			if taken {
				continue
			}
			delete(m, old)
			m[slug] = v
		}
	})
	r.changed("registry", "")
}

func (r *Registry) Repos() []Repo {
	r.promoteLocal(context.Background())
	co := r.checkouts()
	prods := r.Products()
	out := make([]Repo, 0, len(co))
	for slug, path := range co {
		rp := Repo{Slug: slug, Path: path}
		if p, ok := productIn(prods, slug); ok {
			d := p.DocsRepo
			rp.Product = &d
		}
		out = append(out, rp)
	}
	sort.Slice(out, func(i, j int) bool { return strings.ToLower(out[i].Slug) < strings.ToLower(out[j].Slug) })
	return out
}

func (r *Registry) RegisterRepo(ctx context.Context, slug, path string) (Repo, error) {
	if !slugRe.MatchString(slug) {
		return Repo{}, errs.Invalid("slug must look like owner/repo")
	}
	top, err := validateRepo(ctx, path)
	if err != nil {
		return Repo{}, err
	}
	found := originSlug(ctx, top)
	if !eqFold(found, slug) {
		if found == "" {
			found = "not a GitHub repo"
		}
		return Repo{}, errs.Invalid("that folder's origin is %s, not %s", found, slug)
	}
	r.mu.Lock()
	key := slug
	if k, ok := findKey(r.checkouts(), slug); ok {
		key = k
	}
	err = r.setCheckouts(map[string]string{key: top})
	r.mu.Unlock()
	if err != nil {
		return Repo{}, err
	}
	r.changed("registry", key)
	rp := Repo{Slug: key, Path: top}
	if p, ok := r.ProductOf(key); ok {
		d := p.DocsRepo
		rp.Product = &d
	}
	return rp, nil
}

func (r *Registry) RemoveRepo(slug string) error {
	r.mu.Lock()
	removed := false
	err := updateStrings(r.checkoutsFile(), func(m map[string]any) {
		for k := range m {
			if eqFold(k, slug) {
				delete(m, k)
				removed = true
			}
		}
	})
	r.mu.Unlock()
	if err != nil {
		return err
	}
	if !removed {
		return errs.NotFound("%s is not registered", slug)
	}
	r.changed("registry", slug)
	return nil
}

// SlugOf returns the registered slug whose checkout is path ("" when none).
func (r *Registry) SlugOf(path string) string {
	if path == "" {
		return ""
	}
	want := realpath(path)
	co := r.checkouts()
	keys := make([]string, 0, len(co))
	for k := range co {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if co[k] == path || realpath(co[k]) == want {
			return k
		}
	}
	return ""
}

func (r *Registry) slugFor(ctx context.Context, top string) string {
	if s := r.SlugOf(top); s != "" {
		return s
	}
	return originSlug(ctx, top)
}

// Resolve maps a registered slug (any case) or an absolute checkout path to (checkout, slug).
func (r *Registry) Resolve(ctx context.Context, repo string) (string, string, error) {
	if repo == "" {
		return "", "", errs.Invalid("repo is required")
	}
	if k, ok := findKey(r.checkouts(), repo); ok {
		p := r.checkouts()[k]
		if !isDir(p) {
			return "", "", errs.Invalid("%s's checkout is missing: %s", k, p)
		}
		return p, k, nil
	}
	if !filepath.IsAbs(repo) {
		return "", "", errs.Invalid("%s is not a registered repo and not an absolute path", repo)
	}
	top, err := validateRepo(ctx, repo)
	if err != nil {
		return "", "", err
	}
	return top, r.slugFor(ctx, top), nil
}

// DocsRepo returns the Documentation Repo of the checkout at cwd (G§2.2).
func (r *Registry) DocsRepo(ctx context.Context, cwd string) (string, string, error) {
	if !filepath.IsAbs(cwd) {
		if k, ok := findKey(r.checkouts(), cwd); ok {
			cwd = r.checkouts()[k]
		}
	}
	top, err := validateRepo(ctx, cwd)
	if err != nil {
		return "", "", err
	}
	if exists(filepath.Join(top, ".blubird", "repos.json")) {
		return top, r.slugFor(ctx, top), nil
	}
	b, rerr := os.ReadFile(filepath.Join(top, ".blubird", "docs-repo"))
	line := ""
	if rerr == nil {
		line = strings.TrimSpace(strings.SplitN(strings.ReplaceAll(string(b), "\r", ""), "\n", 2)[0])
	}
	if line == "" {
		return "", "", errs.Invalid("%s has no .blubird map or docs-repo pointer: map it, or run /blubird:agentic-onboard", top)
	}
	target := line
	if !filepath.IsAbs(target) {
		target = filepath.Join(top, target)
	}
	dtop, err := validateRepo(ctx, filepath.Clean(target))
	if err != nil {
		return "", "", err
	}
	if !exists(filepath.Join(dtop, ".blubird", "repos.json")) {
		return "", "", errs.Invalid("%s's .blubird/docs-repo points at %s, which has no .blubird/repos.json", top, dtop)
	}
	return dtop, r.slugFor(ctx, dtop), nil
}

// ---- scan ----

var skipDirs = map[string]bool{"node_modules": true, "vendor": true, "venv": true, "dist": true, "build": true,
	"target": true, "Library": true, "Applications": true}

const (
	scanDepth  = 4
	scanBudget = 20 * time.Second
)

// DefaultRoots are the usual places for checkouts that exist on this machine.
func DefaultRoots() []string {
	hd, err := os.UserHomeDir()
	if err != nil {
		return []string{}
	}
	out := []string{}
	for _, rel := range []string{"Documents/Projects", "Projects", "Developer", "code", "work", "dev", "src", "Documents"} {
		if p := filepath.Join(hd, rel); isDir(p) {
			out = append(out, p)
		}
	}
	return out
}

type clone struct{ slug, path string }

// findClones walks the roots (depth <= 4) for dirs with a real .git directory and a GitHub
// origin. It does not descend into clones and stops when ctx ends.
func findClones(ctx context.Context, roots []string) []clone {
	var out []clone
	seen := map[string]bool{}
	for _, root := range roots {
		root = filepath.Clean(root)
		rootDepth := strings.Count(root, string(filepath.Separator))
		_ = filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			if err != nil || !d.IsDir() {
				return nil
			}
			name := d.Name()
			if p != root && (strings.HasPrefix(name, ".") || skipDirs[name]) {
				return filepath.SkipDir
			}
			if st, err := os.Lstat(filepath.Join(p, ".git")); err == nil && st.IsDir() {
				if !seen[p] {
					seen[p] = true
					if slug := originSlug(ctx, p); slug != "" {
						out = append(out, clone{slug, p})
					}
				}
				return filepath.SkipDir
			}
			if strings.Count(p, string(filepath.Separator))-rootDepth >= scanDepth {
				return filepath.SkipDir
			}
			return nil
		})
	}
	return out
}

func (r *Registry) Scan(ctx context.Context, roots []string) (ScanResult, error) {
	if len(roots) == 0 {
		roots = DefaultRoots()
	}
	var use []string
	for _, root := range roots {
		if root == "" || strings.ContainsRune(root, 0) || !filepath.IsAbs(root) || hasDotDot(root) {
			return ScanResult{}, errs.Invalid("scan roots must be absolute paths without '..': %s", root)
		}
		if isDir(root) {
			use = append(use, root)
		}
	}
	sctx, cancel := context.WithTimeout(ctx, scanBudget)
	defer cancel()
	found := findClones(sctx, use)

	res := ScanResult{Added: []Repo{}, Duplicates: []Repo{}}
	r.mu.Lock()
	co := r.checkouts()
	add := map[string]string{}
	for _, c := range found {
		if k, ok := findKey(co, c.slug); ok {
			if co[k] != c.path && realpath(co[k]) != realpath(c.path) {
				res.Duplicates = append(res.Duplicates, Repo{Slug: k, Path: c.path})
			}
			continue
		}
		co[c.slug] = c.path
		add[c.slug] = c.path
		res.Added = append(res.Added, Repo{Slug: c.slug, Path: c.path})
	}
	err := r.setCheckouts(add)
	r.mu.Unlock()
	if err != nil {
		return ScanResult{}, err
	}
	if len(add) > 0 {
		r.changed("registry", "")
	}
	res.Repos = r.Repos()
	prods := r.Products()
	for i := range res.Added {
		if p, ok := productIn(prods, res.Added[i].Slug); ok {
			d := p.DocsRepo
			res.Added[i].Product = &d
		}
	}
	return res, nil
}

// Check runs gh repo view for every registered repo (8 in parallel, 20 s each). nil = fine.
func (r *Registry) Check(ctx context.Context) map[string]*string {
	co := r.checkouts()
	out := make(map[string]*string, len(co))
	var mu sync.Mutex
	var wg sync.WaitGroup
	sem := make(chan struct{}, 8)
	for slug, path := range co {
		wg.Add(1)
		sem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			var problem *string
			set := func(s string) { problem = &s }
			switch {
			case strings.HasPrefix(slug, "local/"):
				set("no GitHub remote")
			case !isDir(path):
				set("folder is missing: " + path)
			default:
				res := execx.Run(ctx, []string{"gh", "repo", "view", slug, "--json", "nameWithOwner"}, execx.Opts{Timeout: 20 * time.Second})
				if res.Code != 0 {
					msg := res.LastLine()
					if msg == "" {
						msg = "gh repo view failed"
					}
					set(msg)
				}
			}
			mu.Lock()
			out[slug] = problem
			mu.Unlock()
		}()
	}
	wg.Wait()
	return out
}

// WatchedRepos is every GitHub slug the poller should watch: the repos of all valid products
// plus registered checkouts outside any product.
func (r *Registry) WatchedRepos() []string {
	seen := map[string]string{}
	add := func(s string) {
		if s == "" || strings.HasPrefix(s, "local/") {
			return
		}
		if _, ok := seen[strings.ToLower(s)]; !ok {
			seen[strings.ToLower(s)] = s
		}
	}
	co := r.checkouts()
	for _, p := range r.Products() {
		if p.Error != "" {
			continue
		}
		if k, ok := findKey(co, p.DocsRepo); ok {
			add(k)
		} else {
			add(p.DocsRepo)
		}
		for _, e := range p.Repos {
			if k, ok := findKey(co, e.Repo); ok {
				add(k)
			} else {
				add(e.Repo)
			}
		}
	}
	for k := range co {
		add(k)
	}
	out := make([]string, 0, len(seen))
	for _, s := range seen {
		out = append(out, s)
	}
	sort.Strings(out)
	return out
}

func itoa(n int) string { return strconv.Itoa(n) }
