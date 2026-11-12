package products

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/masnun-siam/setu/internal/errs"
)

type ProductRepo struct {
	Name     string `json:"name"`
	Role     string `json:"role"`
	Repo     string `json:"repo"`
	Path     string `json:"path"`
	Cloned   bool   `json:"cloned"`
	Conflict string `json:"conflict,omitempty"`
}

type Product struct {
	DocsRepo string        `json:"docs_repo"`
	Name     string        `json:"name"`
	Path     string        `json:"path"`
	Repos    []ProductRepo `json:"repos"`
	Error    string        `json:"error,omitempty"`
}

type mapEntry struct{ Name, Role, Repo, Path string }

type repoMap struct {
	Product string
	Entries []mapEntry
}

// readMap parses <path>/.blubird/repos.json. Error texts are shown as the product's error.
func readMap(path string) (repoMap, error) {
	file := filepath.Join(path, ".blubird", "repos.json")
	b, err := os.ReadFile(file)
	if err != nil {
		return repoMap{}, fmt.Errorf("no .blubird/repos.json in %s", path)
	}
	if !utf8.Valid(b) {
		return repoMap{}, fmt.Errorf("repos.json is not valid UTF-8")
	}
	var v any
	if err := json.Unmarshal(b, &v); err != nil {
		return repoMap{}, fmt.Errorf("repos.json is not valid JSON: %v", err)
	}
	obj, ok := v.(map[string]any)
	if !ok {
		return repoMap{}, fmt.Errorf("repos.json must be a JSON object")
	}
	list, ok := obj["repos"].([]any)
	if !ok || len(list) == 0 {
		return repoMap{}, fmt.Errorf("repos.json must have a non-empty `repos` list")
	}
	m := repoMap{}
	if s, ok := obj["product"].(string); ok {
		m.Product = strings.TrimSpace(s)
	}
	for i, it := range list {
		o, ok := it.(map[string]any)
		if !ok {
			return repoMap{}, fmt.Errorf("repos.json entry %d is not an object", i)
		}
		var vals [4]string
		for j, k := range []string{"name", "role", "repo", "path"} {
			s, ok := o[k].(string)
			if !ok || s == "" || strings.ContainsRune(s, 0) {
				return repoMap{}, fmt.Errorf("repos.json entry %d has no string `%s`", i, k)
			}
			vals[j] = s
		}
		if !slugRe.MatchString(vals[2]) {
			return repoMap{}, fmt.Errorf("repos.json entry %d: repo '%s' is not owner/name", i, vals[2])
		}
		m.Entries = append(m.Entries, mapEntry{vals[0], vals[1], vals[2], vals[3]})
	}
	return m, nil
}

func resolveEntry(docs, p string) string {
	if !filepath.IsAbs(p) {
		p = filepath.Join(docs, p)
	}
	return realpath(p)
}

func defaultName(docsSlug string) string {
	n := docsSlug
	if i := strings.LastIndex(n, "/"); i >= 0 {
		n = n[i+1:]
	}
	for _, suf := range []string{"-docs", "-wiki"} {
		if strings.HasSuffix(n, suf) && len(n) > len(suf) {
			return strings.TrimSuffix(n, suf)
		}
	}
	return n
}

// Products lists every registered product, sorted by docs slug. Pure file reads.
func (r *Registry) Products() []Product {
	rows := readStrings(r.productsFile())
	slugs := make([]string, 0, len(rows))
	for s := range rows {
		slugs = append(slugs, s)
	}
	sort.Slice(slugs, func(i, j int) bool { return strings.ToLower(slugs[i]) < strings.ToLower(slugs[j]) })
	out := make([]Product, 0, len(slugs))
	for _, s := range slugs {
		p := Product{DocsRepo: s, Name: defaultName(s), Path: rows[s], Repos: []ProductRepo{}}
		m, err := readMap(rows[s])
		if err != nil {
			p.Error = err.Error()
			out = append(out, p)
			continue
		}
		if m.Product != "" {
			p.Name = m.Product
		}
		for _, e := range m.Entries {
			p.Repos = append(p.Repos, ProductRepo{Name: e.Name, Role: e.Role, Repo: e.Repo, Path: resolveEntry(rows[s], e.Path),
				Cloned: exists(filepath.Join(resolveEntry(rows[s], e.Path), ".git"))})
		}
		out = append(out, p)
	}
	// conflict: another product's docs repo that also lists (or is) this repo
	for i := range out {
		for j := range out[i].Repos {
			e := &out[i].Repos[j]
			for k := range out {
				if k == i || out[k].Error != "" {
					continue
				}
				hit := eqFold(out[k].DocsRepo, e.Repo)
				for _, o := range out[k].Repos {
					if eqFold(o.Repo, e.Repo) {
						hit = true
					}
				}
				if hit {
					e.Conflict = out[k].DocsRepo
					break
				}
			}
		}
	}
	return out
}

func productIn(ps []Product, slug string) (Product, bool) {
	for _, p := range ps {
		if p.Error != "" {
			continue
		}
		if eqFold(p.DocsRepo, slug) {
			return p, true
		}
		for _, e := range p.Repos {
			if eqFold(e.Repo, slug) {
				return p, true
			}
		}
	}
	return Product{}, false
}

func (r *Registry) ProductOf(slug string) (Product, bool) { return productIn(r.Products(), slug) }

// Register registers the Documentation Repo checked out at docsPath as a product, together with
// every cloned code repo its map lists. Nothing is written until everything validates.
func (r *Registry) Register(ctx context.Context, docsPath string) (Product, error) {
	top, err := validateRepo(ctx, docsPath)
	if err != nil {
		return Product{}, err
	}
	slug := originSlug(ctx, top)
	if slug == "" {
		return Product{}, errs.Invalid("%s has no GitHub origin", top)
	}
	m, err := readMap(top)
	if err != nil {
		return Product{}, errs.Invalid("%s", err.Error())
	}
	co := r.checkouts()
	mapped := map[string]string{strings.ToLower(slug): top}
	type newRepo struct{ repo, path string }
	var add []newRepo
	check := func(repo, p string) error {
		if k, ok := findKey(co, repo); ok && co[k] != p && realpath(co[k]) != p && isDir(co[k]) {
			return errs.Invalid("%s is already registered at %s, the map points at %s", repo, co[k], p)
		}
		return nil
	}
	if err := check(slug, top); err != nil {
		return Product{}, err
	}
	for _, e := range m.Entries {
		p := resolveEntry(top, e.Path)
		if old, ok := mapped[strings.ToLower(e.Repo)]; ok && old != p {
			return Product{}, errs.Invalid("%s is mapped to both %s and %s", e.Repo, old, p)
		}
		if p == top && !eqFold(e.Repo, slug) {
			return Product{}, errs.Invalid("%s points at the docs repo %s itself", e.Repo, slug)
		}
		mapped[strings.ToLower(e.Repo)] = p
		if p == top || !exists(filepath.Join(p, ".git")) {
			continue
		}
		if err := check(e.Repo, p); err != nil {
			return Product{}, err
		}
		ptop, err := validateRepo(ctx, p)
		if err != nil {
			return Product{}, err
		}
		if found := originSlug(ctx, ptop); !eqFold(found, e.Repo) {
			if found == "" {
				found = "not a GitHub repo"
			}
			return Product{}, errs.Invalid("that folder's origin is %s, not %s", found, e.Repo)
		}
		add = append(add, newRepo{e.Repo, ptop})
	}

	r.mu.Lock()
	set := map[string]string{}
	pick := func(repo, p string) {
		key := repo
		if k, ok := findKey(co, repo); ok {
			key = k
		}
		set[key] = p
	}
	pick(slug, top)
	for _, a := range add {
		pick(a.repo, a.path)
	}
	err = r.setCheckouts(set)
	if err == nil {
		err = updateStrings(r.productsFile(), func(pm map[string]any) {
			for k := range pm {
				if eqFold(k, slug) {
					delete(pm, k)
				}
			}
			pm[slug] = top
		})
	}
	r.mu.Unlock()
	if err != nil {
		return Product{}, err
	}
	r.changed("registry", slug)
	for _, p := range r.Products() {
		if p.DocsRepo == slug {
			return p, nil
		}
	}
	return Product{}, errs.NotFound("product %s vanished", slug)
}

// RemoveProduct unregisters a product. Its repo checkouts stay registered.
func (r *Registry) RemoveProduct(docsSlug string) error {
	r.mu.Lock()
	removed := false
	err := updateStrings(r.productsFile(), func(m map[string]any) {
		for k := range m {
			if eqFold(k, docsSlug) {
				delete(m, k)
				removed = true
			}
		}
	})
	r.mu.Unlock()
	if err == nil && removed {
		r.changed("registry", docsSlug)
	}
	return err
}

// Sync registers mapped repos that are not yet known: checkouts that hold a repo map but are not
// products, and cloned repos of known products that are not checkouts. Called every poll tick;
// it only runs git when something is missing. Errors per repo are swallowed.
func (r *Registry) Sync(ctx context.Context) {
	co := r.checkouts()
	rows := readStrings(r.productsFile())
	todo := map[string]bool{}
	keys := make([]string, 0, len(co))
	for k := range co {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if _, isProd := findKey(rows, k); !isProd && exists(filepath.Join(co[k], ".blubird", "repos.json")) {
			todo[co[k]] = true
		}
	}
	for _, p := range r.Products() {
		if p.Error != "" {
			continue
		}
		for _, e := range p.Repos {
			if _, ok := findKey(co, e.Repo); !ok && e.Cloned && e.Conflict == "" {
				todo[p.Path] = true
			}
		}
	}
	docs := make([]string, 0, len(todo))
	for d := range todo {
		docs = append(docs, d)
	}
	sort.Strings(docs)
	for _, d := range docs {
		if ctx.Err() != nil {
			return
		}
		_, _ = r.Register(ctx, d)
	}
}
