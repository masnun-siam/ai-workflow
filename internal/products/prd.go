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

// ReadPRD returns one PRD file of a registered docs checkout. rel must be docs/prds/**/*.md.
func (r *Registry) ReadPRD(repo, rel string) (PRDFile, error) {
	co := r.checkouts()
	key, ok := findKey(co, repo)
	if !ok {
		return PRDFile{}, errs.NotFound("%s is not a registered repo", repo)
	}
	if rel == "" || strings.ContainsRune(rel, 0) || filepath.IsAbs(rel) || hasDotDot(rel) || strings.Contains(rel, `\`) {
		return PRDFile{}, errs.Invalid("bad PRD path")
	}
	clean := filepath.ToSlash(filepath.Clean(rel))
	if !strings.HasPrefix(clean, "docs/prds/") || !strings.HasSuffix(clean, ".md") {
		return PRDFile{}, errs.Invalid("path must be docs/prds/...md")
	}
	base := realpath(co[key])
	abs := realpath(filepath.Join(base, filepath.FromSlash(clean)))
	if !strings.HasPrefix(abs, filepath.Join(base, "docs", "prds")+string(filepath.Separator)) {
		return PRDFile{}, errs.Invalid("bad PRD path")
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
	h := sha1.New()
	fmt.Fprintf(h, "blob %d\x00", len(b))
	h.Write(b)
	branch, _ := gitOut(context.Background(), base, "symbolic-ref", "--short", "-q", "HEAD")
	return PRDFile{Repo: key, Path: clean, Text: string(b), Sha: hex.EncodeToString(h.Sum(nil)), Branch: branch}, nil
}
