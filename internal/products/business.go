package products

import (
	"bufio"
	"context"
	"io"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
)

// BusinessCounts are the rule counts of one business doc (withdrawn rules are in none).
type BusinessCounts struct {
	NotDelivered     int `json:"not_delivered"`
	PartlyDelivered  int `json:"partly_delivered"`
	Drifted          int `json:"drifted"`
	BuiltDifferently int `json:"built_differently"`
	Planned          int `json:"planned"`
	OpenQuestions    int `json:"open_questions"`
}

// BusinessDoc is one docs/business/<module>/<feature>.md of a product's docs checkout.
type BusinessDoc struct {
	Product string         `json:"product"`
	Module  string         `json:"module"`
	Feature string         `json:"feature"`
	Path    string         `json:"path"`
	Title   string         `json:"title"`
	Updated string         `json:"updated"`
	Repos   []string       `json:"repos"`
	Rules   int            `json:"rules"`
	Counts  BusinessCounts `json:"counts"`
	PRDs    []string       `json:"prds"`
	Error   string         `json:"error"`
}

const businessRoot = "docs/business/"

// Ported from blubird 1.2's check-business-docs.py (MARKS, KINDS, EVENT, PLAN_LINK, SKIP_*): marks
// longest first so a prefix never shadows a longer mark.
var (
	bizMarks     = []string{"delivered by later decision", "built differently from the design", "partly delivered", "not delivered", "drifted", "delivered"}
	bizEvent     = regexp.MustCompile(`^- (\d{4}-\d{2}-\d{2})\s+(request|change|decision|design|planned|delivered|withdrawn|validated|observed)\b\s*(\((client|team)\))?\s*(.*)$`)
	bizPRDLink   = regexp.MustCompile(`\]\(([^)]*prds/[^)]+\.md)[^)]*\)`)
	bizRuleID    = regexp.MustCompile(`\bR-\d+\b`)
	bizRuleStart = regexp.MustCompile(`^- \*\*(R-\d+)\b`)
	bizModule    = regexp.MustCompile(`\*\*Module:\*\*\s*([^·|]+?)\s*(?:·|\||$)`)
	bizUpdated   = regexp.MustCompile(`\*\*Updated:\*\*\s*([^·|]+?)\s*(?:·|\||$)`)
	bizRepos     = regexp.MustCompile(`\*\*Repos:\*\*\s*([^·|]+?)\s*(?:·|\||$)`)
	bizTitle     = regexp.MustCompile(`^#\s+(.+?)\s*$`)
	bizSkipFiles = map[string]bool{"readme.md": true, "open-questions-to-client.md": true}
	bizSkipDirs  = map[string]bool{"sources": true, "checklists": true}
)

type bizRule struct {
	id        string
	withdrawn bool
	mark      string
}

// ParseBusinessDoc reads one business doc line by line, keeping counters only. path is the doc's
// repo-relative path; folderModule is the module its folder gives, used when the header has none.
// Parse problems never fail it: the gate reports them.
func ParseBusinessDoc(r io.Reader, docPath, folderModule string) BusinessDoc {
	stem := strings.TrimSuffix(path.Base(docPath), ".md")
	d := BusinessDoc{Module: folderModule, Feature: stem, Path: docPath, Title: stem, Repos: []string{}, PRDs: []string{}}
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64<<10), prdMaxFile+1)
	section, headerDone, titled := "", false, false
	var rules []*bizRule
	var cur *bizRule
	type event struct {
		kind string
		ids  []string
	}
	var events []event
	prds := map[string]bool{}
	for sc.Scan() {
		line := strings.TrimRight(sc.Text(), "\r")
		if strings.HasPrefix(line, "## ") {
			section, cur = strings.ToLower(strings.TrimSpace(line[3:])), nil
			headerDone = true
			continue
		}
		if !headerDone {
			if m := bizTitle.FindStringSubmatch(line); m != nil && !titled {
				d.Title, titled = strings.TrimSuffix(m[1], " — business documentation"), true
			}
			if m := bizModule.FindStringSubmatch(line); m != nil {
				d.Module = strings.TrimSpace(m[1])
			}
			if m := bizUpdated.FindStringSubmatch(line); m != nil {
				d.Updated = strings.TrimSpace(m[1])
			}
			if m := bizRepos.FindStringSubmatch(line); m != nil {
				for _, s := range strings.Split(m[1], ",") {
					if s = strings.TrimSpace(s); s != "" {
						d.Repos = append(d.Repos, s)
					}
				}
			}
			continue
		}
		switch section {
		case "rules":
			if m := bizRuleStart.FindStringSubmatch(line); m != nil {
				// the template writes "Withdrawn by …" in the rule's own line, so it counts there too
				cur = &bizRule{id: m[1], withdrawn: strings.Contains(strings.ToLower(line), "withdrawn by")}
				rules = append(rules, cur)
			} else if cur != nil && strings.HasPrefix(line, "  ") {
				l := strings.TrimSpace(line)
				if strings.Contains(strings.ToLower(l), "withdrawn by") {
					cur.withdrawn = true
				}
				if v, ok := strings.CutPrefix(l, "- Delivery:"); ok && cur.mark == "" {
					v = strings.ToLower(strings.TrimSpace(v))
					for _, mk := range bizMarks {
						if strings.HasPrefix(v, mk) {
							cur.mark = mk
							break
						}
					}
				}
			} else if strings.TrimSpace(line) != "" {
				cur = nil
			}
		case "timeline":
			m := bizEvent.FindStringSubmatch(line)
			if m == nil {
				continue
			}
			kind, rest := m[2], m[5]
			events = append(events, event{kind, bizRuleID.FindAllString(rest, -1)})
			if kind == "planned" {
				for _, l := range bizPRDLink.FindAllStringSubmatch(rest, -1) {
					if p := resolvePRDLink(docPath, l[1]); p != "" {
						prds[p] = true
					}
				}
			}
		case "open questions":
			if strings.HasPrefix(line, "- ") {
				d.Counts.OpenQuestions++
			}
		}
	}
	// planned: a rule whose last planned bullet has no later delivered or withdrawn bullet.
	open := map[string]bool{}
	for _, e := range events {
		for _, id := range e.ids {
			switch e.kind {
			case "planned":
				open[id] = true
			case "delivered", "withdrawn":
				open[id] = false
			}
		}
	}
	for _, r := range rules {
		if r.withdrawn {
			continue
		}
		d.Rules++
		switch r.mark {
		case "not delivered":
			d.Counts.NotDelivered++
		case "partly delivered":
			d.Counts.PartlyDelivered++
		case "drifted":
			d.Counts.Drifted++
		case "built differently from the design":
			d.Counts.BuiltDifferently++
		}
		if open[r.id] {
			d.Counts.Planned++
			open[r.id] = false // a rule id listed twice counts once
		}
	}
	for p := range prds {
		d.PRDs = append(d.PRDs, p)
	}
	sort.Strings(d.PRDs)
	return d
}

// resolvePRDLink resolves a Markdown link target from the doc's folder to a docs/prds/...md path
// ("" when it leaves the repo or is not a PRD).
func resolvePRDLink(docPath, target string) string {
	if i := strings.IndexAny(target, "#? "); i >= 0 {
		target = target[:i]
	}
	if target == "" || strings.Contains(target, "://") || strings.HasPrefix(target, "/") {
		return ""
	}
	p := path.Clean(path.Join(path.Dir(docPath), target))
	if !strings.HasPrefix(p, "docs/prds/") || !strings.HasSuffix(p, ".md") {
		return ""
	}
	return p
}

// BusinessDocs lists docs/business/**/*.md of the product's docs checkout, sorted by path. README.md,
// open-questions-to-client.md and the sources/ and checklists/ folders are not docs (blubird's
// checker skips them too). A missing docs/business gives an empty list.
func (r *Registry) BusinessDocs(product string) ([]BusinessDoc, error) {
	p, err := r.docsCheckout(product)
	if err != nil {
		return nil, err
	}
	root := filepath.Join(p.Path, "docs", "business")
	out := []BusinessDoc{}
	if !isDir(root) {
		return out, nil
	}
	err = filepath.WalkDir(root, func(abs string, de fs.DirEntry, err error) error {
		if err != nil {
			if de != nil && de.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		name := de.Name()
		if de.IsDir() {
			if abs != root && bizSkipDirs[name] {
				return filepath.SkipDir
			}
			return nil
		}
		if !de.Type().IsRegular() || !strings.HasSuffix(name, ".md") || bizSkipFiles[strings.ToLower(name)] {
			return nil
		}
		rel, _ := filepath.Rel(p.Path, abs)
		rel = filepath.ToSlash(rel)
		module := "other"
		if dir, _ := filepath.Rel(root, filepath.Dir(abs)); dir != "." {
			module = filepath.ToSlash(dir)
		}
		d := readBusinessDoc(abs, rel, module)
		d.Product = p.DocsRepo
		out = append(out, d)
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Path < out[j].Path })
	return out, nil
}

func readBusinessDoc(abs, rel, module string) BusinessDoc {
	bad := func(msg string) BusinessDoc {
		d := ParseBusinessDoc(strings.NewReader(""), rel, module)
		d.Error = msg
		return d
	}
	st, err := os.Stat(abs)
	if err != nil {
		return bad("unreadable")
	}
	if st.Size() > prdMaxFile {
		return bad("too large")
	}
	f, err := os.Open(abs)
	if err != nil {
		return bad("unreadable")
	}
	defer f.Close()
	return ParseBusinessDoc(f, rel, module)
}

// businessFile resolves rel (docs/business/**/*.md) inside a registered product's docs checkout:
// the checkout key, its real path and the file's real path.
func (r *Registry) businessFile(repo, rel string) (key, base, abs, clean string, err error) {
	p, err := r.docsCheckout(repo)
	if err != nil {
		return "", "", "", "", err
	}
	if rel == "" || strings.ContainsRune(rel, 0) || filepath.IsAbs(rel) || hasDotDot(rel) || strings.Contains(rel, `\`) {
		return "", "", "", "", errs.Invalid("bad business doc path")
	}
	clean = filepath.ToSlash(filepath.Clean(rel))
	if !strings.HasPrefix(clean, businessRoot) || !strings.HasSuffix(clean, ".md") {
		return "", "", "", "", errs.Invalid("path must be docs/business/...md")
	}
	base = realpath(p.Path)
	abs = realpath(filepath.Join(base, filepath.FromSlash(clean)))
	if !strings.HasPrefix(abs, filepath.Join(base, "docs", "business")+string(filepath.Separator)) {
		return "", "", "", "", errs.NotFound("no such business doc: %s", clean)
	}
	return p.DocsRepo, base, abs, clean, nil
}

// ReadBusiness returns one business doc of a registered product's docs checkout, in the PRDFile
// shape. rel must be docs/business/**/*.md.
func (r *Registry) ReadBusiness(repo, rel string) (PRDFile, error) {
	key, base, abs, clean, err := r.businessFile(repo, rel)
	if err != nil {
		return PRDFile{}, err
	}
	st, err := os.Stat(abs)
	if err != nil || !st.Mode().IsRegular() {
		return PRDFile{}, errs.NotFound("no such business doc: %s", clean)
	}
	if st.Size() > prdMaxFile {
		return PRDFile{}, errs.Invalid("business doc is too large")
	}
	b, err := os.ReadFile(abs)
	if err != nil {
		return PRDFile{}, errs.NotFound("no such business doc: %s", clean)
	}
	branch, _ := gitOut(context.Background(), base, "symbolic-ref", "--short", "-q", "HEAD")
	return PRDFile{Repo: key, Path: clean, Text: string(b), Sha: blobSHA(b), Branch: branch}, nil
}
