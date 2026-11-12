package products

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/server"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

func setup(t *testing.T) (*Registry, string, *events.Bus) {
	t.Helper()
	base := realpath(t.TempDir())
	t.Setenv("HOME", filepath.Join(base, "home"))
	t.Setenv("SETU_HOME", filepath.Join(base, "setu"))
	t.Setenv("GIT_CONFIG_GLOBAL", filepath.Join(base, "gitconfig"))
	t.Setenv("GIT_CONFIG_SYSTEM", "/dev/null")
	h, err := home.Open()
	if err != nil {
		t.Fatal(err)
	}
	bus := events.New()
	ws := filepath.Join(base, "ws")
	os.MkdirAll(ws, 0o755)
	return New(h, nil, bus), ws, bus
}

func run(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", append([]string{"-C", dir, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"}, args...)...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v\n%s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}

// mkRepo creates a git repo at dir with one commit and a GitHub origin.
func mkRepo(t *testing.T, dir, slug string) string {
	t.Helper()
	os.MkdirAll(dir, 0o755)
	run(t, dir, "init", "-q", "-b", "main")
	if slug != "" {
		run(t, dir, "remote", "add", "origin", "https://github.com/"+slug+".git")
	}
	os.WriteFile(filepath.Join(dir, "README"), []byte("x"), 0o644)
	run(t, dir, "add", ".")
	run(t, dir, "commit", "-q", "-m", "init")
	return realpath(dir)
}

func write(t *testing.T, p, s string) {
	t.Helper()
	os.MkdirAll(filepath.Dir(p), 0o755)
	if err := os.WriteFile(p, []byte(s), 0o644); err != nil {
		t.Fatal(err)
	}
}

const mapJSON = `{"repos":[
 {"name":"wiki","role":"docs","repo":"acme/shop-wiki","path":"."},
 {"name":"backend","role":"backend","repo":"acme/shop-api","path":"../shop-api"},
 {"name":"web","role":"frontend","repo":"acme/shop-web","path":"../shop-web"}]}`

// product builds a docs repo with two code repos (only the api cloned).
func product(t *testing.T, ws string) (docs, api string) {
	docs = mkRepo(t, filepath.Join(ws, "shop-wiki"), "acme/shop-wiki")
	api = mkRepo(t, filepath.Join(ws, "shop-api"), "acme/shop-api")
	write(t, filepath.Join(docs, ".blubird", "repos.json"), mapJSON)
	write(t, filepath.Join(api, ".blubird", "docs-repo"), "../shop-wiki\n")
	return
}

func TestReadMapShapes(t *testing.T) {
	dir := t.TempDir()
	cases := []struct{ body, want string }{
		{"", "no .blubird/repos.json in"},
		{"\xff\xfe", "not valid UTF-8"},
		{"{", "not valid JSON"},
		{"[]", "must be a JSON object"},
		{`{"repos":[]}`, "non-empty `repos` list"},
		{`{"repos":{}}`, "non-empty `repos` list"},
		{`{"repos":[1]}`, "entry 0 is not an object"},
		{`{"repos":[{"name":"a","role":"b","repo":"x/y"}]}`, "entry 0 has no string `path`"},
		{`{"repos":[{"name":"","role":"b","repo":"x/y","path":"."}]}`, "no string `name`"},
		{`{"repos":[{"name":"a","role":"b","repo":"xy","path":"."}]}`, "entry 0: repo 'xy' is not owner/name"},
		{`{"repos":[{"name":"a","role":"b","repo":"x/y","path":"."}]}`, ""},
	}
	for _, c := range cases {
		os.RemoveAll(filepath.Join(dir, ".blubird"))
		if c.body != "" {
			write(t, filepath.Join(dir, ".blubird", "repos.json"), c.body)
		}
		_, err := readMap(dir)
		switch {
		case c.want == "" && err != nil:
			t.Errorf("%q: unexpected %v", c.body, err)
		case c.want != "" && (err == nil || !strings.Contains(err.Error(), c.want)):
			t.Errorf("%q: got %v want %q", c.body, err, c.want)
		}
	}
}

func TestRegisterProductIdempotentAndList(t *testing.T) {
	r, ws, _ := setup(t)
	docs, api := product(t, ws)
	p, err := r.Register(context.Background(), docs)
	if err != nil {
		t.Fatal(err)
	}
	if p.DocsRepo != "acme/shop-wiki" || p.Name != "shop" || p.Path != docs || len(p.Repos) != 3 {
		t.Fatalf("%+v", p)
	}
	cloned := map[string]bool{}
	for _, e := range p.Repos {
		cloned[e.Name] = e.Cloned
	}
	if !cloned["wiki"] || !cloned["backend"] || cloned["web"] {
		t.Fatalf("cloned %v", cloned)
	}
	if _, err := r.Register(context.Background(), docs); err != nil {
		t.Fatal(err)
	}
	if n := len(r.Products()); n != 1 {
		t.Fatalf("products %d", n)
	}
	co := r.checkouts()
	if co["acme/shop-wiki"] != docs || co["acme/shop-api"] != api || len(co) != 2 {
		t.Fatalf("checkouts %v", co)
	}
	repos := r.Repos()
	if len(repos) != 2 || repos[0].Slug != "acme/shop-api" || repos[0].Product == nil || *repos[0].Product != "acme/shop-wiki" {
		t.Fatalf("repos %+v", repos)
	}
	if got, ok := r.ProductOf("ACME/shop-web"); !ok || got.DocsRepo != "acme/shop-wiki" {
		t.Fatalf("ProductOf %v %v", got, ok)
	}
	// a map "product" key names the product
	write(t, filepath.Join(docs, ".blubird", "repos.json"), strings.Replace(mapJSON, `{"repos"`, `{"product":"Shopfront","repos"`, 1))
	if r.Products()[0].Name != "Shopfront" {
		t.Fatal("product key ignored")
	}
}

func TestRegisterSymlinkedEntryAndDeletedClone(t *testing.T) {
	r, ws, _ := setup(t)
	docs, api := product(t, ws)
	link := filepath.Join(ws, "link-api")
	os.Symlink(api, link)
	write(t, filepath.Join(docs, ".blubird", "repos.json"),
		`{"repos":[{"name":"wiki","role":"docs","repo":"acme/shop-wiki","path":"."},{"name":"backend","role":"backend","repo":"acme/shop-api","path":"../link-api"}]}`)
	p, err := r.Register(context.Background(), docs)
	if err != nil {
		t.Fatal(err)
	}
	if p.Repos[1].Path != api || !p.Repos[1].Cloned {
		t.Fatalf("%+v", p.Repos[1])
	}
	os.RemoveAll(api)
	if r.Products()[0].Repos[1].Cloned {
		t.Fatal("deleted clone still cloned")
	}
}

func TestRegisterRefusals(t *testing.T) {
	ctx := context.Background()
	cases := []struct {
		name, mapBody, want string
		other               bool // pre-register shop-api somewhere else
	}{
		{"mapped twice", `{"repos":[{"name":"a","role":"b","repo":"acme/shop-api","path":"../shop-api"},{"name":"c","role":"d","repo":"acme/shop-api","path":"../other"}]}`, "is mapped to both", false},
		{"points at docs", `{"repos":[{"name":"a","role":"b","repo":"acme/zzz","path":"."}]}`, "points at the docs repo acme/shop-wiki itself", false},
		{"registered elsewhere", mapJSON, "acme/shop-api is already registered at", true},
		{"wrong origin", `{"repos":[{"name":"a","role":"b","repo":"acme/nope","path":"../shop-api"}]}`, "that folder's origin is acme/shop-api, not acme/nope", false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			r, ws, _ := setup(t)
			docs, _ := product(t, ws)
			write(t, filepath.Join(docs, ".blubird", "repos.json"), c.mapBody)
			if c.other {
				elsewhere := mkRepo(t, filepath.Join(ws, "elsewhere"), "acme/shop-api")
				if _, err := r.RegisterRepo(ctx, "acme/shop-api", elsewhere); err != nil {
					t.Fatal(err)
				}
			}
			before := r.checkouts()
			_, err := r.Register(ctx, docs)
			if err == nil || !strings.Contains(err.Error(), c.want) || errs.KindOf(err) != errs.KInvalid {
				t.Fatalf("got %v want %q", err, c.want)
			}
			if !reflect.DeepEqual(before, r.checkouts()) || len(r.Products()) != 0 {
				t.Fatal("something was written")
			}
		})
	}
	r, ws, _ := setup(t)
	nogh := mkRepo(t, filepath.Join(ws, "plain"), "")
	if _, err := r.Register(ctx, nogh); err == nil || !strings.Contains(err.Error(), "has no GitHub origin") {
		t.Fatalf("%v", err)
	}
	if _, err := r.Register(ctx, t.TempDir()); err == nil || !strings.Contains(err.Error(), "not a git repository") {
		t.Fatalf("%v", err)
	}
	if _, err := r.Register(ctx, "rel/path"); err == nil {
		t.Fatal("relative path accepted")
	}
}

func TestCaseVariantRowsReplaced(t *testing.T) {
	r, ws, _ := setup(t)
	docs, _ := product(t, ws)
	write(t, r.productsFile(), `{"ACME/Shop-Wiki":"/old"}`)
	write(t, r.checkoutsFile(), `{"Acme/Shop-Wiki":"/old","keep/me":"/k","num":5}`)
	if _, err := r.Register(context.Background(), docs); err != nil {
		t.Fatal(err)
	}
	if rows := readStrings(r.productsFile()); len(rows) != 1 || rows["acme/shop-wiki"] != docs {
		t.Fatalf("%v", rows)
	}
	var raw map[string]any
	home.ReadJSON(r.checkoutsFile(), &raw)
	if _, ok := raw["acme/shop-wiki"]; ok || raw["Acme/Shop-Wiki"] != docs || raw["keep/me"] != "/k" || raw["num"] != float64(5) {
		t.Fatalf("%v", raw)
	}
}

func TestConflictAcrossProducts(t *testing.T) {
	r, ws, _ := setup(t)
	docs, _ := product(t, ws)
	other := mkRepo(t, filepath.Join(ws, "other-docs"), "acme/other-docs")
	write(t, filepath.Join(other, ".blubird", "repos.json"),
		`{"repos":[{"name":"d","role":"docs","repo":"acme/other-docs","path":"."},{"name":"b","role":"backend","repo":"acme/shop-api","path":"../shop-api"}]}`)
	ctx := context.Background()
	if _, err := r.Register(ctx, docs); err != nil {
		t.Fatal(err)
	}
	if _, err := r.Register(ctx, other); err != nil {
		t.Fatal(err)
	}
	ps := r.Products()
	if len(ps) != 2 {
		t.Fatal(len(ps))
	}
	for _, p := range ps {
		for _, e := range p.Repos {
			want := ""
			if e.Repo == "acme/shop-api" {
				want = map[string]string{"acme/shop-wiki": "acme/other-docs", "acme/other-docs": "acme/shop-wiki"}[p.DocsRepo]
			}
			if e.Conflict != want {
				t.Errorf("%s/%s conflict %q want %q", p.DocsRepo, e.Repo, e.Conflict, want)
			}
		}
	}
	if ps[0].Name != "other" {
		t.Fatalf("name %q", ps[0].Name)
	}
}

func TestBrokenProductHasError(t *testing.T) {
	r, ws, _ := setup(t)
	docs, _ := product(t, ws)
	r.Register(context.Background(), docs)
	write(t, filepath.Join(docs, ".blubird", "repos.json"), "{nope")
	p := r.Products()[0]
	if !strings.Contains(p.Error, "not valid JSON") || p.Repos == nil {
		t.Fatalf("%+v", p)
	}
	if _, ok := r.ProductOf("acme/shop-wiki"); ok {
		t.Fatal("errored product matched")
	}
	b, _ := json.Marshal(p)
	if !strings.Contains(string(b), `"repos":[]`) {
		t.Fatal(string(b))
	}
}

func TestRemoveProductAndRepo(t *testing.T) {
	r, ws, _ := setup(t)
	docs, _ := product(t, ws)
	r.Register(context.Background(), docs)
	r.RemoveProduct("ACME/shop-wiki")
	if len(r.Products()) != 0 || len(r.checkouts()) != 2 {
		t.Fatal("remove product")
	}
	if err := r.RemoveRepo("ACME/SHOP-API"); err != nil {
		t.Fatal(err)
	}
	if err := r.RemoveRepo("acme/shop-api"); errs.KindOf(err) != errs.KNotFound {
		t.Fatalf("%v", err)
	}
}

func TestLegacyFilesAndSync(t *testing.T) {
	r, ws, _ := setup(t)
	docs, api := product(t, ws)
	// old registry files as migrated: checkouts only, plus a stray non-string value
	write(t, r.checkoutsFile(), `{"acme/shop-wiki":"`+docs+`","x/y":3}`)
	if got := r.Repos(); len(got) != 1 || got[0].Slug != "acme/shop-wiki" || got[0].Product != nil {
		t.Fatalf("%+v", got)
	}
	if w := r.WatchedRepos(); !reflect.DeepEqual(w, []string{"acme/shop-wiki"}) {
		t.Fatalf("%v", w)
	}
	r.Sync(context.Background())
	got := r.Repos()
	if len(got) != 2 || got[0].Product == nil {
		t.Fatalf("after sync %+v", got)
	}
	if len(r.Products()) != 1 || r.checkouts()["acme/shop-api"] != api {
		t.Fatal("sync did not register product + code repo")
	}
	if w := r.WatchedRepos(); !reflect.DeepEqual(w, []string{"acme/shop-api", "acme/shop-web", "acme/shop-wiki"}) {
		t.Fatalf("%v", w)
	}
}

func TestPromoteLocal(t *testing.T) {
	r, ws, _ := setup(t)
	d := mkRepo(t, filepath.Join(ws, "app"), "acme/app")
	write(t, r.checkoutsFile(), `{"local/app":"`+d+`","local/gone":"/nonexistent"}`)
	got := r.Repos()
	if len(got) != 2 || got[0].Slug != "acme/app" || got[1].Slug != "local/gone" {
		t.Fatalf("%+v", got)
	}
}

func TestRegisterRepoAndResolve(t *testing.T) {
	r, ws, bus := setup(t)
	ch, cancel := bus.Subscribe(8)
	defer cancel()
	ctx := context.Background()
	d := mkRepo(t, filepath.Join(ws, "app"), "Acme/App")
	if _, err := r.RegisterRepo(ctx, "bad", d); err == nil || !strings.Contains(err.Error(), "owner/repo") {
		t.Fatal(err)
	}
	if _, err := r.RegisterRepo(ctx, "acme/other", d); err == nil || !strings.Contains(err.Error(), "origin is Acme/App, not acme/other") {
		t.Fatal(err)
	}
	rp, err := r.RegisterRepo(ctx, "acme/app", d)
	if err != nil || rp.Slug != "acme/app" {
		t.Fatalf("%v %+v", err, rp)
	}
	if ev := <-ch; ev.Topic != events.TProducts {
		t.Fatalf("%+v", ev)
	}
	// re-registering with another spelling keeps the registered one
	if rp, _ := r.RegisterRepo(ctx, "ACME/APP", d); rp.Slug != "acme/app" {
		t.Fatal(rp.Slug)
	}
	sub := filepath.Join(d, "sub")
	os.MkdirAll(sub, 0o755)
	for _, in := range []string{"ACME/App", d, sub} {
		p, s, err := r.Resolve(ctx, in)
		if err != nil || p != d || s != "acme/app" {
			t.Errorf("Resolve(%q) = %q %q %v", in, p, s, err)
		}
	}
	for _, in := range []string{"", "nope/nope", "rel", d + "/../x", t.TempDir()} {
		if _, _, err := r.Resolve(ctx, in); errs.KindOf(err) != errs.KInvalid {
			t.Errorf("Resolve(%q) = %v", in, err)
		}
	}
	free := mkRepo(t, filepath.Join(ws, "free"), "acme/free")
	if p, s, err := r.Resolve(ctx, free); err != nil || p != free || s != "acme/free" {
		t.Fatalf("%q %q %v", p, s, err)
	}
	if r.SlugOf(sub) != "" || r.SlugOf(d) != "acme/app" || r.SlugOf("") != "" {
		t.Fatal("SlugOf")
	}
}

func TestDocsRepo(t *testing.T) {
	r, ws, _ := setup(t)
	ctx := context.Background()
	docs, api := product(t, ws)
	r.Register(ctx, docs)
	for _, cwd := range []string{docs, api, filepath.Join(api, "..", "shop-api")[:0] + api} {
		p, s, err := r.DocsRepo(ctx, cwd)
		if err != nil || p != docs || s != "acme/shop-wiki" {
			t.Errorf("DocsRepo(%q) = %q %q %v", cwd, p, s, err)
		}
	}
	// monorepo: the repo is its own docs repo
	mono := mkRepo(t, filepath.Join(ws, "mono"), "acme/mono")
	write(t, filepath.Join(mono, ".blubird", "repos.json"), `{"repos":[{"name":"all","role":"docs","repo":"acme/mono","path":"."}]}`)
	if p, s, err := r.DocsRepo(ctx, mono); err != nil || p != mono || s != "acme/mono" {
		t.Fatalf("%q %q %v", p, s, err)
	}
	if _, err := r.Register(ctx, mono); err != nil {
		t.Fatal(err)
	}
	// errors
	bare := mkRepo(t, filepath.Join(ws, "bare"), "acme/bare")
	if _, _, err := r.DocsRepo(ctx, bare); err == nil || !strings.Contains(err.Error(), "has no .blubird map or docs-repo pointer: map it, or run /blubird:agentic-onboard") {
		t.Fatal(err)
	}
	nomap := mkRepo(t, filepath.Join(ws, "nomap"), "acme/nomap")
	write(t, filepath.Join(bare, ".blubird", "docs-repo"), "../nomap\n")
	if _, _, err := r.DocsRepo(ctx, bare); err == nil || !strings.Contains(err.Error(), "points at "+nomap+", which has no .blubird/repos.json") {
		t.Fatal(err)
	}
	write(t, filepath.Join(bare, ".blubird", "docs-repo"), "../missing\n")
	if _, _, err := r.DocsRepo(ctx, bare); errs.KindOf(err) != errs.KInvalid {
		t.Fatal(err)
	}
	write(t, filepath.Join(bare, ".blubird", "docs-repo"), "\n")
	if _, _, err := r.DocsRepo(ctx, bare); err == nil || !strings.Contains(err.Error(), "no .blubird map") {
		t.Fatal(err)
	}
}

func TestScan(t *testing.T) {
	r, ws, _ := setup(t)
	ctx := context.Background()
	root := filepath.Join(ws, "projects")
	a := mkRepo(t, filepath.Join(root, "a"), "acme/a")
	mkRepo(t, filepath.Join(root, "group", "b"), "acme/b")
	dup := mkRepo(t, filepath.Join(root, "z-copy"), "acme/a") // second clone of a: duplicate
	mkRepo(t, filepath.Join(root, "node_modules", "n"), "acme/n")
	mkRepo(t, filepath.Join(root, ".hidden", "h"), "acme/h")
	mkRepo(t, filepath.Join(root, "1", "2", "3", "4", "deep"), "acme/deep")
	mkRepo(t, filepath.Join(root, "noorigin"), "")
	inner := mkRepo(t, filepath.Join(root, "a", "inner"), "acme/inner") // inside a clone: not descended
	_ = inner
	// a worktree (.git file) is not a clone
	run(t, a, "worktree", "add", "-q", filepath.Join(root, "wt"), "-b", "wt")

	res, err := r.Scan(ctx, []string{root})
	if err != nil {
		t.Fatal(err)
	}
	var added []string
	for _, x := range res.Added {
		added = append(added, x.Slug)
	}
	if !reflect.DeepEqual(added, []string{"acme/a", "acme/b"}) {
		t.Fatalf("added %v", added)
	}
	if len(res.Duplicates) != 1 || res.Duplicates[0].Slug != "acme/a" || res.Duplicates[0].Path != dup {
		t.Fatalf("dups %+v", res.Duplicates)
	}
	if len(res.Repos) != 2 {
		t.Fatalf("repos %+v", res.Repos)
	}
	// second scan finds nothing new
	res, _ = r.Scan(ctx, []string{root})
	if len(res.Added) != 0 || len(res.Duplicates) != 1 {
		t.Fatalf("%+v", res)
	}
	for _, bad := range [][]string{{"rel"}, {root + "/../x"}} {
		if _, err := r.Scan(ctx, bad); errs.KindOf(err) != errs.KInvalid {
			t.Errorf("%v: %v", bad, err)
		}
	}
	// a cancelled context stops the walk (budget)
	cctx, cancel := context.WithCancel(ctx)
	cancel()
	if got := findClones(cctx, []string{root}); len(got) != 0 {
		t.Fatalf("walk ignored ctx: %v", got)
	}
}

func TestCheck(t *testing.T) {
	r, ws, _ := setup(t)
	dir := t.TempDir()
	fakebin.Install(t, dir)
	fakebin.WriteRules(t, dir, []fakebin.Rule{
		{Bin: "gh", ArgsContains: "repo view acme/ok", Stdout: `{"nameWithOwner":"acme/ok"}`},
		{Bin: "gh", ArgsContains: "repo view acme/bad", Stderr: "Could not resolve to a Repository\n", Exit: 1},
	})
	ok := mkRepo(t, filepath.Join(ws, "ok"), "acme/ok")
	bad := mkRepo(t, filepath.Join(ws, "bad"), "acme/bad")
	write(t, r.checkoutsFile(), `{"acme/ok":"`+ok+`","acme/bad":"`+bad+`","local/x":"`+ok+`","acme/gone":"/nonexistent"}`)
	got := r.Check(context.Background())
	if got["acme/ok"] != nil {
		t.Errorf("ok: %v", *got["acme/ok"])
	}
	if p := got["acme/bad"]; p == nil || !strings.Contains(*p, "Could not resolve") {
		t.Errorf("bad: %v", p)
	}
	if p := got["local/x"]; p == nil || *p != "no GitHub remote" {
		t.Errorf("local: %v", p)
	}
	if p := got["acme/gone"]; p == nil || !strings.Contains(*p, "missing") {
		t.Errorf("gone: %v", p)
	}
}

const prdA = "# PRD — Checkout flow\n\n**Status:** In review · **Date:** 2026-01-01 · **Slug:** `checkout-flow` · **Owner:** x\n\nbody"

func TestParsePRD(t *testing.T) {
	cases := []struct{ head, stem, status, slug, title string }{
		{prdA, "f", "In review", "checkout-flow", "Checkout flow"},
		{"# Plain title\n**Status:** approved\n", "stem", "Approved", "stem", "Plain title"},
		{"# PRD: Colon\n**Status:** Done | x\n**Slug:** abc.d\n", "s", "Done", "abc.d", "Colon"},
		{"no heading", "only-stem", "Draft", "only-stem", "only-stem"},
		{"**Status:** Weird\n", "s", "Draft", "s", "s"},
		{"# T\n**Status:** Draft", "s", "Draft", "s", "T"},
	}
	for _, c := range cases {
		st, sl, ti := ParsePRD(c.head, c.stem)
		if st != c.status || sl != c.slug || ti != c.title {
			t.Errorf("%q -> %q %q %q", c.head, st, sl, ti)
		}
	}
}

func TestPRDsNestedAndReadPRD(t *testing.T) {
	r, ws, _ := setup(t)
	docs, _ := product(t, ws)
	write(t, filepath.Join(docs, "docs/prds/README.md"), "# PRDs\n")
	write(t, filepath.Join(docs, "docs/prds/flat.md"), "# Flat\n**Status:** Draft\n")
	write(t, filepath.Join(docs, "docs/prds/checkout/flow.md"), prdA)
	write(t, filepath.Join(docs, "docs/prds/checkout/deep/x.md"), "# X\n**Status:** Done\n")
	write(t, filepath.Join(docs, "docs/prds/checkout/notes.txt"), "no")
	write(t, filepath.Join(docs, "docs/prds/.git-ignored/h.md"), "# H")
	r.Register(context.Background(), docs)

	prds, err := r.PRDs("ACME/shop-wiki")
	if err != nil {
		t.Fatal(err)
	}
	type row struct{ path, module, slug, status, label string }
	var got []row
	for _, p := range prds {
		m := "<nil>"
		if p.Module != nil {
			m = *p.Module
		}
		if p.Product != "acme/shop-wiki" || p.Epic != nil {
			t.Errorf("%+v", p)
		}
		got = append(got, row{p.Path, m, p.Slug, p.Status, p.Label})
	}
	want := []row{
		{"docs/prds/checkout/deep/x.md", "checkout/deep", "x", "Done", "prd-x"},
		{"docs/prds/checkout/flow.md", "checkout", "checkout-flow", "In review", "prd-checkout-flow"},
		{"docs/prds/flat.md", "<nil>", "flat", "Draft", "prd-flat"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("%+v", got)
	}
	if _, err := r.PRDs("nope/nope"); errs.KindOf(err) != errs.KNotFound {
		t.Fatal(err)
	}

	f, err := r.ReadPRD("acme/shop-wiki", "docs/prds/checkout/flow.md")
	if err != nil || f.Text != prdA || f.Branch != "main" || len(f.Sha) != 40 || f.Repo != "acme/shop-wiki" {
		t.Fatalf("%+v %v", f, err)
	}
	if want := run(t, docs, "hash-object", "docs/prds/checkout/flow.md"); f.Sha != want {
		t.Fatalf("sha %s want %s", f.Sha, want)
	}
	for _, bad := range []string{"", "../secret.md", "docs/prds/../../x.md", "/etc/passwd", "docs/other.md", "docs/prds/checkout/notes.txt", "docs/prds/x\x00.md"} {
		if _, err := r.ReadPRD("acme/shop-wiki", bad); errs.KindOf(err) != errs.KInvalid && errs.KindOf(err) != errs.KNotFound {
			t.Errorf("%q accepted: %v", bad, err)
		}
	}
	// a symlink out of docs/prds is refused
	os.WriteFile(filepath.Join(ws, "secret.md"), []byte("s"), 0o644)
	os.Symlink(filepath.Join(ws, "secret.md"), filepath.Join(docs, "docs/prds/leak.md"))
	if _, err := r.ReadPRD("acme/shop-wiki", "docs/prds/leak.md"); err == nil {
		t.Fatal("symlink escape")
	}
	if _, err := r.ReadPRD("acme/shop-wiki", "docs/prds/missing.md"); errs.KindOf(err) != errs.KNotFound {
		t.Fatal(err)
	}
	if _, err := r.ReadPRD("who/dis", "docs/prds/flat.md"); errs.KindOf(err) != errs.KNotFound {
		t.Fatal(err)
	}
}

// ---- cleanup ----

func worktreeFor(t *testing.T, repo string, n int, name string) (wt, branch string) {
	t.Helper()
	branch = "issue-" + string(rune('0'+n)) + "-" + name
	wt = filepath.Join(repo, ".worktrees", string(rune('0'+n))+"-"+name)
	run(t, repo, "worktree", "add", "-q", wt, "-b", branch)
	return realpath(wt), branch
}

func TestCleanup(t *testing.T) {
	r, ws, _ := setup(t)
	repo := mkRepo(t, filepath.Join(ws, "app"), "acme/app")
	bare := filepath.Join(ws, "remote.git")
	run(t, ws, "init", "-q", "--bare", bare)
	run(t, repo, "remote", "add", "up", bare)
	run(t, repo, "push", "-q", "up", "main")

	t.Run("nothing to clean", func(t *testing.T) {
		removed, flags, err := r.Cleanup(repo, 9, false, "")
		if err != nil || flags != nil || len(removed) != 0 || r.CleanupCheck(repo, 9, "") != nil {
			t.Fatalf("%v %v %v", removed, flags, err)
		}
	})
	t.Run("clean worktree removed", func(t *testing.T) {
		wt, br := worktreeFor(t, repo, 1, "clean")
		if f := r.CleanupCheck(repo, 1, ""); f != nil {
			t.Fatalf("%+v", f)
		}
		removed, flags, err := r.Cleanup(repo, 1, false, "")
		if err != nil || flags != nil || !reflect.DeepEqual(removed, []string{wt, "branch " + br}) {
			t.Fatalf("%v %v %v", removed, flags, err)
		}
		if isDir(wt) || run(t, repo, "branch", "--list", br) != "" {
			t.Fatal("still there")
		}
	})
	t.Run("flagged needs confirm", func(t *testing.T) {
		wt, br := worktreeFor(t, repo, 2, "dirty")
		write(t, filepath.Join(wt, "wip.txt"), "x")
		write(t, filepath.Join(wt, "node_modules", "pkg", "i.js"), "x") // regenerable: ignored by the check
		write(t, filepath.Join(wt, ".gitignore"), "")                   // untracked, counts
		run(t, wt, "commit", "--allow-empty", "-q", "-m", "local only")
		removed, flags, err := r.Cleanup(repo, 2, false, "")
		if err != nil || len(removed) != 0 || flags == nil {
			t.Fatalf("%v %v %v", removed, flags, err)
		}
		if !reflect.DeepEqual(flags.Uncommitted, []string{".gitignore", "wip.txt"}) || len(flags.Unpushed) != 1 {
			t.Fatalf("%+v", flags)
		}
		if !isDir(wt) {
			t.Fatal("removed without confirm")
		}
		removed, _, _ = r.Cleanup(repo, 2, true, "")
		if !reflect.DeepEqual(removed, []string{wt, "branch " + br}) || isDir(wt) {
			t.Fatalf("%v", removed)
		}
	})
	t.Run("merged head counts as pushed", func(t *testing.T) {
		wt, _ := worktreeFor(t, repo, 3, "merged")
		run(t, wt, "commit", "--allow-empty", "-q", "-m", "work")
		head := run(t, wt, "rev-parse", "HEAD")
		if f := r.CleanupCheck(repo, 3, ""); f == nil || len(f.Unpushed) != 1 {
			t.Fatalf("%+v", f)
		}
		if f := r.CleanupCheck(repo, 3, head); f != nil {
			t.Fatalf("%+v", f)
		}
		if f := r.CleanupCheck(repo, 3, strings.Repeat("0", 40)); f == nil { // unknown sha is not excluded
			t.Fatal("unknown sha excluded")
		}
	})
	t.Run("never the checked-out branch", func(t *testing.T) {
		run(t, repo, "checkout", "-q", "-b", "issue-5-main")
		removed, _, _ := r.Cleanup(repo, 5, true, "")
		if len(removed) != 0 || run(t, repo, "branch", "--list", "issue-5-main") == "" {
			t.Fatalf("%v", removed)
		}
		run(t, repo, "checkout", "-q", "main")
	})
	t.Run("branch only, no worktree", func(t *testing.T) {
		run(t, repo, "branch", "issue-6-solo")
		removed, _, _ := r.Cleanup(repo, 6, true, "")
		if !reflect.DeepEqual(removed, []string{"branch issue-6-solo"}) {
			t.Fatalf("%v", removed)
		}
	})
	t.Run("never outside .worktrees", func(t *testing.T) {
		out := filepath.Join(ws, "outside")
		run(t, repo, "worktree", "add", "-q", out, "-b", "issue-7-out")
		removed, _, _ := r.Cleanup(repo, 7, true, "")
		if !isDir(out) {
			t.Fatal("removed a worktree outside .worktrees/")
		}
		for _, x := range removed {
			if x == out {
				t.Fatal(removed)
			}
		}
		// the branch is checked out in that worktree, so branch -D fails too
		if run(t, repo, "branch", "--list", "issue-7-out") == "" {
			t.Fatal("branch gone")
		}
	})
	t.Run("never remotes", func(t *testing.T) {
		_, br := worktreeFor(t, repo, 8, "pushed")
		run(t, repo, "push", "-q", "up", br)
		removed, _, _ := r.Cleanup(repo, 8, true, "")
		if len(removed) != 2 {
			t.Fatalf("%v", removed)
		}
		if run(t, bare, "branch", "--list", br) == "" {
			t.Fatal("remote branch deleted")
		}
	})
	t.Run("missing checkout", func(t *testing.T) {
		removed, flags, err := r.Cleanup(filepath.Join(ws, "nope"), 1, true, "")
		if err != nil || flags != nil || len(removed) != 0 {
			t.Fatal(removed, flags, err)
		}
	})
}

// ---- routes ----

type env struct {
	mux  *http.ServeMux
	reg  *Registry
	ws   string
	deps Deps
}

func newEnv(t *testing.T, mut func(*Deps)) *env {
	r, ws, _ := setup(t)
	d := Deps{Reg: r, ScanRoots: func() []string { return []string{ws} }}
	if mut != nil {
		mut(&d)
	}
	mux := http.NewServeMux()
	for _, rt := range Routes(d) {
		mux.Handle(rt.Pattern, rt.Handler)
	}
	return &env{mux, r, ws, d}
}

func (e *env) do(method, path, body string) (int, map[string]any) {
	var rd *strings.Reader
	if body == "" {
		rd = strings.NewReader("")
	} else {
		rd = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, path, rd)
	if method == http.MethodPost {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("Host", "127.0.0.1")
	w := httptest.NewRecorder()
	e.mux.ServeHTTP(w, req)
	var m map[string]any
	json.Unmarshal(w.Body.Bytes(), &m)
	return w.Code, m
}

var _ = server.Route{}

func TestRoutes(t *testing.T) {
	var merged = map[int]string{}
	var pickStart string
	e := newEnv(t, func(d *Deps) {
		d.Merged = func(repo string, n int) (string, bool) { h, ok := merged[n]; return h, ok }
		d.Pick = func(ctx context.Context, start string) (string, error) {
			pickStart = start
			return "/picked", nil
		}
	})
	docs, api := product(t, e.ws)

	code, m := e.do("POST", "/api/products", `{"path":"`+docs+`"}`)
	if code != 201 || m["docs_repo"] != "acme/shop-wiki" {
		t.Fatalf("%d %v", code, m)
	}
	if code, m = e.do("POST", "/api/products", `{"path":"/nope"}`); code != 400 || m["error"] == nil {
		t.Fatalf("%d %v", code, m)
	}
	code, m = e.do("GET", "/api/products", "")
	if code != 200 || len(m["products"].([]any)) != 1 {
		t.Fatalf("%d %v", code, m)
	}
	code, m = e.do("GET", "/api/repos", "")
	if code != 200 || len(m["repos"].([]any)) != 2 || m["scan_roots"].([]any)[0] != e.ws {
		t.Fatalf("%d %v", code, m)
	}
	if _, ok := m["can_browse"].(bool); !ok {
		t.Fatal("can_browse")
	}
	// register
	other := mkRepo(t, filepath.Join(e.ws, "x"), "acme/x")
	code, m = e.do("POST", "/api/repos", `{"slug":"acme/x","path":"`+other+`"}`)
	if code != 200 || m["repo"].(map[string]any)["slug"] != "acme/x" || len(m["repos"].([]any)) != 3 {
		t.Fatalf("%d %v", code, m)
	}
	if code, _ = e.do("POST", "/api/repos", `{"slug":"bad","path":"`+other+`"}`); code != 400 {
		t.Fatal(code)
	}
	code, m = e.do("DELETE", "/api/repos/acme/x", "")
	if code != 200 || len(m["repos"].([]any)) != 2 {
		t.Fatalf("%d %v", code, m)
	}
	if code, _ = e.do("DELETE", "/api/repos/acme/x", ""); code != 404 {
		t.Fatal(code)
	}
	// scan finds the (unregistered) x again
	code, m = e.do("POST", "/api/repos/scan", `{}`)
	if code != 200 || len(m["added"].([]any)) != 1 || m["added"].([]any)[0].(map[string]any)["slug"] != "acme/x" {
		t.Fatalf("%d %v", code, m)
	}
	if code, _ = e.do("POST", "/api/repos/scan", `{"roots":["rel"]}`); code != 400 {
		t.Fatal(code)
	}
	// browse
	code, m = e.do("POST", "/api/repos/browse", `{"start":"`+e.ws+`"}`)
	if code != 200 || m["path"] != "/picked" || pickStart != e.ws {
		t.Fatalf("%d %v %q", code, m, pickStart)
	}
	e.do("POST", "/api/repos/browse", `{"start":"rel/../x"}`)
	if pickStart != "" {
		t.Fatalf("bad start passed: %q", pickStart)
	}
	// prds
	write(t, filepath.Join(docs, "docs/prds/m/f.md"), prdA)
	code, m = e.do("GET", "/api/products/acme/shop-wiki/prds", "")
	if code != 200 || len(m["prds"].([]any)) != 1 {
		t.Fatalf("%d %v", code, m)
	}
	if code, _ = e.do("GET", "/api/products/acme/zzz/prds", ""); code != 404 {
		t.Fatal(code)
	}
	code, m = e.do("GET", "/api/prd?repo=acme/shop-wiki&path=docs/prds/m/f.md", "")
	if code != 200 || m["text"] != prdA {
		t.Fatalf("%d %v", code, m)
	}
	for _, q := range []string{"?repo=bad&path=docs/prds/m/f.md", "?repo=acme/shop-wiki&path=../x.md", "?repo=acme/shop-wiki"} {
		if code, _ = e.do("GET", "/api/prd"+q, ""); code != 400 {
			t.Errorf("%s: %d", q, code)
		}
	}
	// cleanup
	wt, _ := worktreeFor(t, api, 4, "thing")
	if code, m = e.do("POST", "/api/repos/acme/shop-api/cleanup", `{"issue":4,"confirm":true}`); code != 409 || m["error"] != "#4's PR is not merged" {
		t.Fatalf("%d %v", code, m)
	}
	merged[4] = "abc"
	if code, _ = e.do("POST", "/api/repos/acme/shop-api/cleanup", `{"issue":4,"confirm":false}`); code != 400 {
		t.Fatal(code)
	}
	if code, _ = e.do("POST", "/api/repos/acme/shop-api/cleanup", `{"issue":0,"confirm":true}`); code != 400 {
		t.Fatal(code)
	}
	if code, _ = e.do("POST", "/api/repos/acme/none/cleanup", `{"issue":4,"confirm":true}`); code != 404 {
		t.Fatal(code)
	}
	code, m = e.do("POST", "/api/repos/acme/shop-api/cleanup", `{"issue":4,"confirm":true}`)
	if code != 200 || len(m["removed"].([]any)) != 2 || isDir(wt) {
		t.Fatalf("%d %v", code, m)
	}
	// check (gh missing from fake rules → every repo reports a problem, none panic)
	fb := t.TempDir()
	fakebin.Install(t, fb)
	fakebin.WriteRules(t, fb, []fakebin.Rule{{Bin: "gh", Stdout: "{}"}})
	code, m = e.do("POST", "/api/repos/check", `{}`)
	if code != 200 || len(m["problems"].(map[string]any)) != 3 {
		t.Fatalf("%d %v", code, m)
	}
	// delete product
	code, m = e.do("DELETE", "/api/products/acme/shop-wiki", "")
	if code != 200 || len(m["products"].([]any)) != 0 {
		t.Fatalf("%d %v", code, m)
	}
}

func TestBrowseForbiddenWhenNotLocal(t *testing.T) {
	e := newEnv(t, nil)
	req := httptest.NewRequest("POST", "/api/repos/browse", strings.NewReader(`{}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Tailscale-User-Login", "me@x")
	w := httptest.NewRecorder()
	e.mux.ServeHTTP(w, req)
	if w.Code != 403 || !strings.Contains(w.Body.String(), "only available locally on macOS") {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
}

func TestSavePRDCommitsOnlyThatFile(t *testing.T) {
	r, ws, _ := setup(t)
	write(t, os.Getenv("GIT_CONFIG_GLOBAL"), "[user]\n\tname = t\n\temail = t@t\n[commit]\n\tgpgsign = false\n")
	docs, _ := product(t, ws)
	write(t, filepath.Join(docs, "docs/prds/checkout/flow.md"), prdA)
	run(t, docs, "add", ".")
	run(t, docs, "commit", "-q", "-m", "prd")
	write(t, filepath.Join(docs, "other.txt"), "staged but not part of the edit")
	run(t, docs, "add", "other.txt")
	r.Register(context.Background(), docs)
	ctx := context.Background()

	f, err := r.ReadPRD("acme/shop-wiki", "docs/prds/checkout/flow.md")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := r.SavePRD(ctx, "acme/shop-wiki", f.Path, "x", "0000000000000000000000000000000000000000"); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("stale base accepted: %v", err)
	}
	got, err := r.SavePRD(ctx, "acme/shop-wiki", f.Path, prdA+"\nMore.\n", f.Sha)
	if err != nil {
		t.Fatal(err)
	}
	if got.Sha == f.Sha || !strings.HasSuffix(got.Text, "More.\n") {
		t.Fatalf("%+v", got)
	}
	if files := run(t, docs, "show", "--name-only", "--format=", "HEAD"); files != "docs/prds/checkout/flow.md" {
		t.Fatalf("commit touched %q", files)
	}
	if st := run(t, docs, "status", "--porcelain"); st != "A  other.txt" {
		t.Fatalf("index changed: %q", st)
	}
	if _, err := r.SavePRD(ctx, "acme/shop-wiki", "docs/prds/../x.md", "x", got.Sha); errs.KindOf(err) != errs.KInvalid {
		t.Fatal(err)
	}
}

func TestCreateLocalThenPublish(t *testing.T) {
	r, ws, _ := setup(t)
	write(t, os.Getenv("GIT_CONFIG_GLOBAL"), "[user]\n\tname = t\n\temail = t@t\n[commit]\n\tgpgsign = false\n")
	ctx := context.Background()
	rp, err := r.CreateLocal(ctx, "notes-app", ws, []byte("# Notes\n**Status:** Draft\n"), "payouts")
	if err != nil {
		t.Fatal(err)
	}
	if rp.Slug != "local/notes-app" {
		t.Fatalf("%+v", rp)
	}
	if files := run(t, rp.Path, "ls-files"); files != "README.md\ndocs/prds/payouts.md" {
		t.Fatalf("files %q", files)
	}
	for _, bad := range [][2]string{{"../x", ws}, {"ok", "relative"}, {"notes-app", ws}} {
		if _, err := r.CreateLocal(ctx, bad[0], bad[1], nil, ""); err == nil {
			t.Errorf("%v accepted", bad)
		}
	}

	var got []string
	orig := ghRun
	t.Cleanup(func() { ghRun = orig })
	ghRun = func(_ context.Context, args []string, _ time.Duration) execx.Result {
		got = args
		run(t, rp.Path, "remote", "add", "origin", "https://github.com/acme/notes-app.git")
		return execx.Result{Code: 0}
	}
	pub, err := r.Publish(ctx, "local/notes-app", "acme", "notes-app", true)
	if err != nil {
		t.Fatal(err)
	}
	if pub.Slug != "acme/notes-app" || strings.Join(got, " ") != "repo create acme/notes-app --private --source "+rp.Path+" --remote origin --push" {
		t.Fatalf("%+v %v", pub, got)
	}
	if _, err := r.Publish(ctx, "acme/notes-app", "acme", "x", false); errs.KindOf(err) != errs.KInvalid {
		t.Fatal(err)
	}
}
