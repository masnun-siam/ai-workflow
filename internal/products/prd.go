package products

import (
	"context"
	"crypto/sha1"
	"encoding/hex"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/home"
)

type PRD struct {
	Product string  `json:"product"`
	Module  *string `json:"module"`
	Slug    string  `json:"slug"`
	Title   string  `json:"title"`
	Status  string  `json:"status"`
	Path    string  `json:"path"`
	Label   string  `json:"label"`
	Epic    *string `json:"epic"`
}

type PRDFile struct {
	Repo   string `json:"repo"`
	Path   string `json:"path"`
	Text   string `json:"text"`
	Sha    string `json:"sha"`
	Branch string `json:"branch"`
}

const (
	prdHead    = 4000
	prdMaxFile = 2 << 20
)

var (
	statusRe = regexp.MustCompile(`(?m)\*\*Status:\*\*\s*([A-Za-z ]+?)\s*(?:·|\||$)`)
	slugLine = regexp.MustCompile("(?m)\\*\\*Slug:\\*\\*\\s*`?([A-Za-z0-9._-]+)`?")
	titleRe  = regexp.MustCompile(`(?m)^#\s+(?:PRD\s*[—–:-]\s*)?(.+?)\s*$`)
	statuses = map[string]string{"draft": "Draft", "in review": "In review", "approved": "Approved", "done": "Done"}
)

// ParsePRD reads status, slug and title from the head of a PRD. stem is the file name without .md.
func ParsePRD(head, stem string) (status, slug, title string) {
	status = "Draft"
	if m := statusRe.FindStringSubmatch(head); m != nil {
		if s, ok := statuses[strings.ToLower(strings.TrimSpace(m[1]))]; ok {
			status = s
		}
	}
	slug, title = stem, stem
	if m := slugLine.FindStringSubmatch(head); m != nil {
		slug = m[1]
	}
	if m := titleRe.FindStringSubmatch(head); m != nil {
		title = m[1]
	}
	return
}

func (r *Registry) docsCheckout(product string) (Product, error) {
	for _, p := range r.Products() {
		if eqFold(p.DocsRepo, product) {
			return p, nil
		}
	}
	return Product{}, errs.NotFound("%s is not a registered product", product)
}

// PRDs lists docs/prds/**/*.md of the product's docs checkout, sorted by path. A README.md is not
// a PRD. The module is the folder under docs/prds (nil for a file directly in it).
func (r *Registry) PRDs(product string) ([]PRD, error) {
	p, err := r.docsCheckout(product)
	if err != nil {
		return nil, err
	}
	root := filepath.Join(p.Path, "docs", "prds")
	out := []PRD{}
	if !isDir(root) {
		return out, nil
	}
	err = filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			if d != nil && d.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		if d.IsDir() {
			if path != root && strings.HasPrefix(d.Name(), ".") {
				return filepath.SkipDir
			}
			return nil
		}
		name := d.Name()
		if !d.Type().IsRegular() || !strings.HasSuffix(name, ".md") || strings.EqualFold(name, "README.md") {
			return nil
		}
		f, err := os.Open(path)
		if err != nil {
			return nil
		}
		buf, _ := io.ReadAll(io.LimitReader(f, prdHead))
		f.Close()
		stem := strings.TrimSuffix(name, ".md")
		status, slug, title := ParsePRD(strings.ToValidUTF8(string(buf), ""), stem)
		rel, _ := filepath.Rel(p.Path, path)
		prd := PRD{Product: p.DocsRepo, Slug: slug, Title: title, Status: status, Path: filepath.ToSlash(rel), Label: "prd-" + slug}
		if dir, _ := filepath.Rel(root, filepath.Dir(path)); dir != "." {
			m := filepath.ToSlash(dir)
			prd.Module = &m
		}
		out = append(out, prd)
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Path < out[j].Path })
	return out, nil
}

// prdFile resolves rel (docs/prds/**/*.md) inside a registered checkout: the checkout key, its
// real path and the file's real path.
func (r *Registry) prdFile(repo, rel string) (key, base, abs, clean string, err error) {
	co := r.checkouts()
	key, ok := findKey(co, repo)
	if !ok {
		return "", "", "", "", errs.NotFound("%s is not a registered repo", repo)
	}
	if rel == "" || strings.ContainsRune(rel, 0) || filepath.IsAbs(rel) || hasDotDot(rel) || strings.Contains(rel, `\`) {
		return "", "", "", "", errs.Invalid("bad PRD path")
	}
	clean = filepath.ToSlash(filepath.Clean(rel))
	if !strings.HasPrefix(clean, "docs/prds/") || !strings.HasSuffix(clean, ".md") {
		return "", "", "", "", errs.Invalid("path must be docs/prds/...md")
	}
	base = realpath(co[key])
	abs = realpath(filepath.Join(base, filepath.FromSlash(clean)))
	if !strings.HasPrefix(abs, filepath.Join(base, "docs", "prds")+string(filepath.Separator)) {
		return "", "", "", "", errs.Invalid("bad PRD path")
	}
	return key, base, abs, clean, nil
}

func blobSHA(b []byte) string {
	h := sha1.New()
	fmt.Fprintf(h, "blob %d\x00", len(b))
	h.Write(b)
	return hex.EncodeToString(h.Sum(nil))
}

// ReadPRD returns one PRD file of a registered docs checkout. rel must be docs/prds/**/*.md.
func (r *Registry) ReadPRD(repo, rel string) (PRDFile, error) {
	key, base, abs, clean, err := r.prdFile(repo, rel)
	if err != nil {
		return PRDFile{}, err
	}
	st, err := os.Stat(abs)
	if err != nil || !st.Mode().IsRegular() {
		return PRDFile{}, errs.NotFound("no such PRD: %s", clean)
	}
	if st.Size() > prdMaxFile {
		return PRDFile{}, errs.Invalid("PRD is too large")
	}
	b, err := os.ReadFile(abs)
	if err != nil {
		return PRDFile{}, errs.NotFound("no such PRD: %s", clean)
	}
	branch, _ := gitOut(context.Background(), base, "symbolic-ref", "--short", "-q", "HEAD")
	return PRDFile{Repo: key, Path: clean, Text: string(b), Sha: blobSHA(b), Branch: branch}, nil
}

// SavePRD writes an existing PRD and commits only that file on the checkout's current branch (it
// never pushes). baseSHA is the blob sha the edit started from: a different file on disk is a
// conflict, so a concurrent change (a create-prd run, a pull) is never overwritten.
func (r *Registry) SavePRD(ctx context.Context, repo, rel, text, baseSHA string) (PRDFile, error) {
	if strings.ContainsRune(text, 0) || len(text) > prdMaxFile {
		return PRDFile{}, errs.Invalid("text must be under 2 MiB with no NUL")
	}
	cur, err := r.ReadPRD(repo, rel)
	if err != nil {
		return PRDFile{}, err
	}
	if baseSHA == "" || cur.Sha != baseSHA {
		return PRDFile{}, errs.Conflict("the PRD changed since you opened it: reload it and edit again", map[string]any{"sha": cur.Sha})
	}
	if cur.Text == text {
		return cur, nil
	}
	_, base, abs, clean, err := r.prdFile(repo, rel)
	if err != nil {
		return PRDFile{}, err
	}
	st, _ := os.Stat(abs)
	if err := home.AtomicWrite(abs, []byte(text), st.Mode().Perm()); err != nil {
		return PRDFile{}, err
	}
	if res := git(ctx, base, "add", "--", clean); res.Code != 0 {
		return PRDFile{}, errs.Upstream("git add failed: %s", strings.TrimSpace(string(res.Stderr)))
	}
	if res := git(ctx, base, "commit", "--only", "-m", "docs(prd): edit "+clean+" in setu", "--", clean); res.Code != 0 {
		return PRDFile{}, errs.Upstream("saved, but git commit failed: %s", strings.TrimSpace(string(res.Stderr)+string(res.Stdout)))
	}
	return r.ReadPRD(repo, rel)
}
