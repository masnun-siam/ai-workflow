package products

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/masnun-siam/setu/internal/errs"
)

// bizDoc covers every Delivery mark, every Timeline kind, a withdrawn rule, a rule with no mark,
// planned-then-delivered, planned-then-withdrawn, planned-still-open, a PRD link and an issue link.
const bizDoc = `# Login — business documentation

**Module:** auth · **Updated:** 2026-11-01 · **Repos:** api, web

## What it does

Signs people in.

## Rules

- **R-1 Delivered.** x
  - Acceptance: a
  - Delivery: delivered — api@abc1234
  - Sources: s
- **R-2 Partly.** x
  - Delivery: Partly delivered — PR #4
- **R-3 Not.** x
  - Delivery: not delivered — planned
- **R-4 Drifted.** x
  - Delivery: drifted — #9
- **R-5 Built differently.** x
  - Delivery: built differently from the design — #10
- **R-6 Later decision.** x
  - Delivery: delivered by later decision — #11
- **R-7 Gone.** Withdrawn by 2026-10-01 decision
  - Delivery: not delivered — x
- **R-8 No mark.** x
  - Delivery: someday
- **R-9 Withdrawn below.** x
  - Delivery: drifted — #12
  - Note: withdrawn by the team
Not a rule line.
  - Delivery: drifted — ignored, outside any block

## Open questions

- Who signs in?
- When?

## Timeline

- 2026-01-01 request (client) R-1 asked ` + "`s.md:1`" + `
- 2026-01-02 change (team) R-1 changed ` + "`s.md:2`" + `
- 2026-01-03 decision (client) R-1 decided ` + "`s.md:3`" + `
- 2026-01-04 design (team) R-1 designed ` + "`s.md:4`" + `
- 2026-01-05 planned (team) R-2 PRD [login](../../prds/auth/login.md#fr-2)
- 2026-01-06 planned (team) R-3 #12
- 2026-01-07 planned (team) R-4 R-7 PRD [other](../../prds/auth/other.md)
- 2026-01-08 delivered R-2 api@abc1234
- 2026-01-09 planned (team) R-5 acme/api#3
- 2026-01-10 withdrawn R-5 ` + "`s.md:5`" + `
- 2026-01-11 validated R-1 api@abc1234
- 2026-01-12 observed R-6 api@abc1234
- 2026-01-13 delivered R-3 api@abc1234
- 2026-01-14 planned (team) R-3 again [x](https://example.com/prds/x.md)
- 2026-01-15 planned (team) R-8 [up](../../../outside/prds/a.md)
- undated bullet R-1
`

func TestParseBusinessDoc(t *testing.T) {
	d := ParseBusinessDoc(strings.NewReader(bizDoc), "docs/business/auth/login.md", "folder")
	want := BusinessDoc{Module: "auth", Feature: "login", Path: "docs/business/auth/login.md", Title: "Login", Updated: "2026-11-01",
		Repos: []string{"api", "web"}, Rules: 7,
		Counts: BusinessCounts{NotDelivered: 1, PartlyDelivered: 1, Drifted: 1, BuiltDifferently: 1, Planned: 3, OpenQuestions: 2},
		PRDs:   []string{"docs/prds/auth/login.md", "docs/prds/auth/other.md"}}
	// planned: R-3 (re-planned after its delivery), R-4, R-8; not R-2 (delivered), R-5 (withdrawn), R-7 (rule withdrawn)
	if !reflect.DeepEqual(d, want) {
		t.Fatalf("got  %+v\nwant %+v", d, want)
	}

	none := "# Bare\n\n## Rules\n\n- **R-1 A.** x\n\n## Open questions\n\nNone\n"
	d = ParseBusinessDoc(strings.NewReader(none), "docs/business/bare.md", "other")
	if d.Module != "other" || d.Title != "Bare" || d.Rules != 1 || d.Counts != (BusinessCounts{}) || d.Repos == nil || d.PRDs == nil {
		t.Fatalf("%+v", d)
	}
	d = ParseBusinessDoc(strings.NewReader("\xff\xfe garbage\n## Timeline\n- nope"), "docs/business/m/x.md", "m")
	if d.Feature != "x" || d.Module != "m" || d.Title != "x" || d.Rules != 0 {
		t.Fatalf("malformed %+v", d)
	}
}

func TestResolvePRDLink(t *testing.T) {
	for in, want := range map[string]string{
		"../../prds/a/b.md":       "docs/prds/a/b.md",
		"../../prds/a/b.md#fr-1":  "docs/prds/a/b.md",
		"../../../docs/prds/b.md": "docs/prds/b.md",
		"../../../../prds/b.md":   "",
		"/docs/prds/b.md":         "",
		"https://x/prds/b.md":     "",
		"../../prds/a/b.txt":      "",
	} {
		if got := resolvePRDLink("docs/business/auth/login.md", in); got != want {
			t.Errorf("%s: %q want %q", in, got, want)
		}
	}
}

func TestBusinessDocsWalk(t *testing.T) {
	r, ws, _ := setup(t)
	docs, _ := product(t, ws)
	if _, err := r.Register(context.Background(), docs); err != nil {
		t.Fatal(err)
	}
	if got, err := r.BusinessDocs("acme/shop-wiki"); err != nil || got == nil || len(got) != 0 {
		t.Fatalf("no docs/business: %v %v", got, err)
	}
	b := filepath.Join(docs, "docs", "business")
	write(t, filepath.Join(b, "auth/login.md"), bizDoc)
	write(t, filepath.Join(b, "auth/signup.md"), "# Signup — business documentation\n\n**Module:** auth\n\n## Rules\n\n- **R-1 A.** x\n  - Delivery: not delivered — y\n")
	write(t, filepath.Join(b, "billing/plans.md"), "# Plans\n\n## Rules\n\n- **R-1 A.** x\n")
	write(t, filepath.Join(b, "top.md"), "# Top\n")
	for _, skip := range []string{"README.md", "Open-Questions-To-Client.md", "auth/readme.md", "sources/x.md", "auth/checklists/y.md", "auth/notes.txt", ".hidden/z.md"} {
		write(t, filepath.Join(b, skip), "# skip\n")
	}
	big := filepath.Join(b, "billing/huge.md")
	write(t, big, "# Huge\n")
	if err := os.Truncate(big, prdMaxFile+1); err != nil {
		t.Fatal(err)
	}

	got, err := r.BusinessDocs("ACME/shop-wiki")
	if err != nil {
		t.Fatal(err)
	}
	type row struct {
		path, module, feature, title, err string
		rules, notDelivered               int
	}
	var rows []row
	for _, d := range got {
		if d.Product != "acme/shop-wiki" {
			t.Errorf("product %q", d.Product)
		}
		rows = append(rows, row{d.Path, d.Module, d.Feature, d.Title, d.Error, d.Rules, d.Counts.NotDelivered})
	}
	want := []row{
		{"docs/business/auth/login.md", "auth", "login", "Login", "", 7, 1},
		{"docs/business/auth/signup.md", "auth", "signup", "Signup", "", 1, 1},
		{"docs/business/billing/huge.md", "billing", "huge", "huge", "too large", 0, 0},
		{"docs/business/billing/plans.md", "billing", "plans", "Plans", "", 1, 0},
		{"docs/business/top.md", "other", "top", "Top", "", 0, 0},
	}
	if !reflect.DeepEqual(rows, want) {
		t.Fatalf("got  %+v\nwant %+v", rows, want)
	}
	if _, err := r.BusinessDocs("nope/nope"); errs.KindOf(err) != errs.KNotFound {
		t.Fatal(err)
	}
}

func TestReadBusiness(t *testing.T) {
	r, ws, _ := setup(t)
	docs, api := product(t, ws)
	r.Register(context.Background(), docs)
	write(t, filepath.Join(docs, "docs/business/auth/login.md"), bizDoc)
	write(t, filepath.Join(docs, "docs/business/a.txt"), "x")
	write(t, filepath.Join(docs, "docs/prds/a.md"), "# A\n")
	write(t, filepath.Join(api, "docs/business/auth/x.md"), "# api doc\n")

	f, err := r.ReadBusiness("acme/shop-wiki", "docs/business/auth/login.md")
	if err != nil || f.Text != bizDoc || f.Branch != "main" || f.Repo != "acme/shop-wiki" || f.Path != "docs/business/auth/login.md" {
		t.Fatalf("%+v %v", f, err)
	}
	if want := run(t, docs, "hash-object", "docs/business/auth/login.md"); f.Sha != want {
		t.Fatalf("sha %s want %s", f.Sha, want)
	}
	big := filepath.Join(docs, "docs/business/big.md")
	write(t, big, "x")
	os.Truncate(big, prdMaxFile+1)
	os.WriteFile(filepath.Join(ws, "secret.md"), []byte("s"), 0o644)
	os.Symlink(filepath.Join(ws, "secret.md"), filepath.Join(docs, "docs/business/leak.md"))
	os.Symlink(filepath.Join(docs, "docs/prds/a.md"), filepath.Join(docs, "docs/business/prd.md"))

	cases := []struct {
		repo, path string
		kind       errs.Kind
	}{
		{"acme/shop-wiki", "", errs.KInvalid},
		{"acme/shop-wiki", "../x.md", errs.KInvalid},
		{"acme/shop-wiki", "docs/business/../../x.md", errs.KInvalid},
		{"acme/shop-wiki", "/etc/passwd", errs.KInvalid},
		{"acme/shop-wiki", "docs/business/x\x00.md", errs.KInvalid},
		{"acme/shop-wiki", "docs/prds/a.md", errs.KInvalid},
		{"acme/shop-wiki", "docs/business/a.txt", errs.KInvalid},
		{"acme/shop-wiki", "docs/business/big.md", errs.KInvalid},
		{"acme/shop-wiki", "docs/business/missing.md", errs.KNotFound},
		{"acme/shop-wiki", "docs/business/leak.md", errs.KNotFound},
		{"acme/shop-wiki", "docs/business/prd.md", errs.KNotFound},
		{"who/dis", "docs/business/auth/login.md", errs.KNotFound},
		{"acme/shop-api", "docs/business/auth/x.md", errs.KNotFound}, // a code repo, not a docs checkout
	}
	for _, c := range cases {
		if _, err := r.ReadBusiness(c.repo, c.path); errs.KindOf(err) != c.kind {
			t.Errorf("%s %q: %v, want kind %v", c.repo, c.path, err, c.kind)
		}
	}
}

func TestBusinessRoute(t *testing.T) {
	e := newEnv(t, nil)
	docs, _ := product(t, e.ws)
	e.reg.Register(context.Background(), docs)
	write(t, filepath.Join(docs, "docs/business/auth/login.md"), bizDoc)

	code, m := e.do("GET", "/api/business?repo=acme/shop-wiki&path=docs/business/auth/login.md", "")
	if code != 200 || m["text"] != bizDoc || m["repo"] != "acme/shop-wiki" || m["branch"] != "main" || len(m["sha"].(string)) != 40 {
		t.Fatalf("%d %v", code, m)
	}
	for path, want := range map[string]int{
		"/api/business?repo=acme/shop-wiki&path=docs/business/../x.md": 400,
		"/api/business?repo=bad&path=docs/business/auth/login.md":      400,
		"/api/business?repo=acme/shop-wiki&path=docs/business/no.md":   404,
		"/api/business?repo=who/dis&path=docs/business/auth/login.md":  404,
	} {
		if code, m := e.do("GET", path, ""); code != want || m["error"] == nil {
			t.Errorf("%s: %d %v", path, code, m)
		}
	}
}
