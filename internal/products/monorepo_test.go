package products

import (
	"context"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/events"
)

const monoMap = `{
  "repos": [
    {
      "name": "app",
      "role": "docs",
      "repo": "acme/app",
      "path": "."
    }
  ]
}
`

func readFile(t *testing.T, p string) string {
	t.Helper()
	b, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func repoRow(t *testing.T, r *Registry, slug string) Repo {
	t.Helper()
	for _, rp := range r.Repos() {
		if rp.Slug == slug {
			return rp
		}
	}
	t.Fatalf("%s not listed", slug)
	return Repo{}
}

func TestMapStateAndReposMap(t *testing.T) {
	e := newEnv(t, nil)
	docs, api := product(t, e.ws)
	bare := mkRepo(t, filepath.Join(e.ws, "bare"), "acme/bare")
	write(t, e.reg.checkoutsFile(), `{"acme/shop-wiki":"`+docs+`","acme/shop-api":"`+api+`","acme/bare":"`+bare+`"}`)
	code, m := e.do("GET", "/api/repos", "")
	if code != 200 {
		t.Fatal(code)
	}
	got := map[string]any{}
	for _, it := range m["repos"].([]any) {
		row := it.(map[string]any)
		got[row["slug"].(string)] = row["map"]
	}
	want := map[string]any{"acme/shop-wiki": "docs", "acme/shop-api": "pointer", "acme/bare": "none"}
	for k, v := range want {
		if got[k] != v {
			t.Errorf("%s: map %v, want %v", k, got[k], v)
		}
	}
}

func TestMonorepoEndpoint(t *testing.T) {
	e := newEnv(t, nil)
	app := mkRepo(t, filepath.Join(e.ws, "app"), "acme/app")
	if _, err := e.reg.RegisterRepo(context.Background(), "acme/app", app); err != nil {
		t.Fatal(err)
	}
	head := run(t, app, "rev-parse", "HEAD")
	code, m := e.do("POST", "/api/repos/acme/app/monorepo", `{}`)
	if code != 201 {
		t.Fatalf("%d %v", code, m)
	}
	p := m["product"].(map[string]any)
	if p["docs_repo"] != "acme/app" || p["map_committed"] != false || len(p["repos"].([]any)) != 1 {
		t.Fatalf("%v", p)
	}
	file := filepath.Join(app, ".blubird", "repos.json")
	if got := readFile(t, file); got != monoMap {
		t.Fatalf("map %q", got)
	}
	if st, _ := os.Stat(filepath.Dir(file)); st.Mode().Perm() != 0o755 {
		t.Fatalf(".blubird mode %v", st.Mode().Perm())
	}
	if st, _ := os.Stat(file); st.Mode().Perm() != 0o644 {
		t.Fatalf("repos.json mode %v", st.Mode().Perm())
	}
	if h := run(t, app, "rev-parse", "HEAD"); h != head {
		t.Fatal("HEAD moved")
	}
	if st := run(t, app, "status", "--porcelain"); st != "?? .blubird/" {
		t.Fatalf("status %q", st)
	}
	if code, m = e.do("GET", "/api/products", ""); code != 200 || len(m["products"].([]any)) != 1 {
		t.Fatalf("%d %v", code, m)
	}
	if rp := repoRow(t, e.reg, "acme/app"); rp.Map != MapDocs || rp.Product == nil || *rp.Product != "acme/app" {
		t.Fatalf("%+v", rp)
	}

	// the identical map: 200, file untouched
	st1, _ := os.Stat(file)
	time.Sleep(20 * time.Millisecond)
	code, m = e.do("POST", "/api/repos/ACME/app/monorepo", `{}`)
	if code != 200 || m["product"].(map[string]any)["docs_repo"] != "acme/app" {
		t.Fatalf("%d %v", code, m)
	}
	st2, _ := os.Stat(file)
	if readFile(t, file) != monoMap || !st1.ModTime().Equal(st2.ModTime()) {
		t.Fatal("identical map was rewritten")
	}
}

func TestMonorepoConcurrent(t *testing.T) {
	e := newEnv(t, nil)
	app := mkRepo(t, filepath.Join(e.ws, "app"), "acme/app")
	if _, err := e.reg.RegisterRepo(context.Background(), "acme/app", app); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	codes := make([]int, 2)
	for i := range codes {
		wg.Add(1)
		go func() {
			defer wg.Done()
			codes[i], _ = e.do("POST", "/api/repos/acme/app/monorepo", `{}`)
		}()
	}
	wg.Wait()
	if (codes[0] != 201 || codes[1] != 200) && (codes[0] != 200 || codes[1] != 201) {
		t.Fatalf("codes %v", codes)
	}
	if readFile(t, filepath.Join(app, ".blubird", "repos.json")) != monoMap {
		t.Fatal("map")
	}
	if left, _ := filepath.Glob(filepath.Join(app, ".blubird", ".*tmp*")); len(left) != 0 {
		t.Fatalf("temp files left: %v", left)
	}
}

func TestMonorepoRefusals(t *testing.T) {
	e := newEnv(t, nil)
	ctx := context.Background()
	reg := func(slug, dir string) string {
		t.Helper()
		p := mkRepo(t, filepath.Join(e.ws, dir), slug)
		if _, err := e.reg.RegisterRepo(ctx, slug, p); err != nil {
			t.Fatal(err)
		}
		return p
	}
	expect := func(path string, code int, msg string) {
		t.Helper()
		got, m := e.do("POST", path, `{}`)
		if got != code || m["error"] != msg {
			t.Errorf("%s: %d %v, want %d %q", path, got, m, code, msg)
		}
	}
	expect("/api/repos/acme/nope/monorepo", 404, "acme/nope is not a registered repo")

	local := mkRepo(t, filepath.Join(e.ws, "scratch"), "")
	write(t, e.reg.checkoutsFile(), `{"local/scratch":"`+local+`"}`)
	expect("/api/repos/local/scratch/monorepo", 400, "local/scratch has no GitHub origin: add a remote first")
	if exists(filepath.Join(local, ".blubird")) {
		t.Fatal("local repo written")
	}

	other := reg("acme/other", "other")
	diff := `{"repos":[{"name":"other","role":"docs","repo":"acme/other","path":"."},{"name":"x","role":"web","repo":"acme/x","path":"../x"}]}`
	write(t, filepath.Join(other, ".blubird", "repos.json"), diff)
	expect("/api/repos/acme/other/monorepo", 409, "acme/other already has a repo map or docs-repo pointer")
	if readFile(t, filepath.Join(other, ".blubird", "repos.json")) != diff {
		t.Fatal("different map changed")
	}

	ptr := reg("acme/ptr", "ptr")
	write(t, filepath.Join(ptr, ".blubird", "docs-repo"), "../missing\n")
	expect("/api/repos/acme/ptr/monorepo", 409, "acme/ptr already has a repo map or docs-repo pointer")
	if exists(filepath.Join(ptr, ".blubird", "repos.json")) {
		t.Fatal("map written next to a pointer")
	}

	// a code repo of another product, with no pointer of its own
	docs, api := product(t, e.ws)
	if _, err := e.reg.Register(ctx, docs); err != nil {
		t.Fatal(err)
	}
	os.RemoveAll(filepath.Join(api, ".blubird"))
	expect("/api/repos/acme/shop-api/monorepo", 409, "acme/shop-api is already part of product acme/shop-wiki")
	if exists(filepath.Join(api, ".blubird")) {
		t.Fatal("code repo written")
	}
	if code, _ := e.do("POST", "/api/repos/acme/x/monorepo", ``); code != 400 {
		t.Fatalf("empty body: %d", code)
	}
}

func TestMapCommitted(t *testing.T) {
	r, ws, bus := setup(t)
	ctx := context.Background()
	app := mkRepo(t, filepath.Join(ws, "app"), "acme/app")
	if _, err := r.RegisterRepo(ctx, "acme/app", app); err != nil {
		t.Fatal(err)
	}
	p, wrote, err := r.Monorepo(ctx, "acme/app")
	if err != nil || !wrote || p.MapCommitted {
		t.Fatalf("%+v %v %v", p, wrote, err)
	}
	committed := func() bool {
		t.Helper()
		p, ok := r.ProductOf("acme/app")
		if !ok {
			t.Fatal("no product")
		}
		return p.MapCommitted
	}
	r.Sync(ctx)
	if committed() {
		t.Fatal("untracked map reads committed")
	}
	run(t, app, "add", ".blubird/repos.json")
	r.Sync(ctx)
	if committed() {
		t.Fatal("staged map reads committed")
	}
	ch, cancel := bus.Subscribe(8)
	defer cancel()
	run(t, app, "commit", "-q", "-m", "map")
	r.Sync(ctx)
	if !committed() {
		t.Fatal("committed map reads not committed")
	}
	select {
	case ev := <-ch:
		if ev.Topic != events.TProducts {
			t.Fatalf("%+v", ev)
		}
	case <-time.After(time.Second):
		t.Fatal("no registry event when map_committed flipped")
	}
	// no further event while nothing changes
	r.Sync(ctx)
	select {
	case ev := <-ch:
		t.Fatalf("unexpected %+v", ev)
	default:
	}

	// a product not cached yet, and a product with an error, read as true
	docs, _ := product(t, ws)
	if _, err := r.Register(ctx, docs); err != nil {
		t.Fatal(err)
	}
	if p, _ := r.ProductOf("acme/shop-wiki"); !p.MapCommitted {
		t.Fatal("uncached product reads not committed")
	}
	os.Remove(filepath.Join(docs, ".blubird", "repos.json"))
	for _, p := range r.Products() {
		if p.DocsRepo == "acme/shop-wiki" && (p.Error == "" || !p.MapCommitted) {
			t.Fatalf("%+v", p)
		}
	}
}

func TestNeedsMap(t *testing.T) {
	r, ws, _ := setup(t)
	ctx := context.Background()
	bare := mkRepo(t, filepath.Join(ws, "bare"), "acme/bare")
	mapped := mkRepo(t, filepath.Join(ws, "mapped"), "acme/mapped")
	write(t, filepath.Join(mapped, ".blubird", "repos.json"), `{"repos":[{"name":"mapped","role":"docs","repo":"acme/mapped","path":"."}]}`)
	ptr := mkRepo(t, filepath.Join(ws, "ptr"), "acme/ptr")
	write(t, filepath.Join(ptr, ".blubird", "docs-repo"), "../missing\n")
	docs, api := product(t, ws)
	os.RemoveAll(filepath.Join(api, ".blubird"))
	noOrigin := mkRepo(t, filepath.Join(ws, "noorigin"), "")
	for slug, p := range map[string]string{"acme/bare": bare, "acme/mapped": mapped, "acme/ptr": ptr} {
		if _, err := r.RegisterRepo(ctx, slug, p); err != nil {
			t.Fatal(err)
		}
	}
	if _, err := r.Register(ctx, docs); err != nil {
		t.Fatal(err)
	}
	cases := []struct {
		repo, slug string
		needs      bool
	}{
		{"acme/bare", "acme/bare", true},
		{"ACME/BARE", "acme/bare", true},
		{bare, "acme/bare", true},
		{"acme/mapped", "acme/mapped", false},
		{"acme/ptr", "acme/ptr", false},
		{"acme/shop-api", "acme/shop-api", false},
		{noOrigin, "", false},
		{"acme/unknown", "", false},
	}
	for _, c := range cases {
		if s, n := r.NeedsMap(ctx, c.repo); s != c.slug || n != c.needs {
			t.Errorf("NeedsMap(%q) = %q %v, want %q %v", c.repo, s, n, c.slug, c.needs)
		}
	}
}

func TestRegisterRepoReportsMap(t *testing.T) {
	r, ws, _ := setup(t)
	app := mkRepo(t, filepath.Join(ws, "app"), "acme/app")
	if rp, err := r.RegisterRepo(context.Background(), "acme/app", app); err != nil || rp.Map != MapNone {
		t.Fatalf("%+v %v", rp, err)
	}
}
