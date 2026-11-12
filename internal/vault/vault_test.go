package vault

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

type fs struct{ dir string }

func (f fs) VaultDir() string   { return f.dir }
func (f fs) DefaultCmd() string { return "claude" }

func mk(t *testing.T, paths ...string) string {
	t.Helper()
	v := t.TempDir()
	for _, p := range paths {
		if err := os.MkdirAll(filepath.Join(v, p), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	return v
}

func TestValidFolder(t *testing.T) {
	long := strings.Repeat("a", 121)
	for f, want := range map[string]bool{
		"05-Work/Proj": true, "05-Work/Proj/Feat": true, "05-Work/A b/C d": true,
		"05-Work": false, "05-Work/": false, "05-Work/P/F/G": false, "05-Work/.git": false,
		"05-Work/P/.hidden": false, "05-Work/..": false, "05-Work/P/..": false, "05-Work/.": false,
		"04-Other/P": false, "/05-Work/P": false, "05-Work/" + long: false, "05-Work//F": false,
		"05-Work/P\x00": false, "../05-Work/P": false,
	} {
		if got := ValidFolder(f); got != want {
			t.Errorf("ValidFolder(%q) = %v, want %v", f, got, want)
		}
	}
}

func TestFolders(t *testing.T) {
	v := mk(t, "05-Work/Beta/Login", "05-Work/Alpha", "05-Work/.hidden/x", "05-Work/Beta/.git", "05-Work/Alpha/Sub")
	_ = os.WriteFile(filepath.Join(v, "05-Work", "file.txt"), nil, 0o644)
	got, err := New(Deps{Settings: fs{v}}).Folders()
	if err != nil {
		t.Fatal(err)
	}
	var paths []string
	for _, f := range got {
		paths = append(paths, f.Path)
	}
	want := "05-Work/Alpha,05-Work/Alpha/Sub,05-Work/Beta,05-Work/Beta/Login"
	if strings.Join(paths, ",") != want {
		t.Fatalf("paths = %v", paths)
	}
	if got[0].Feature != nil || got[1].Feature == nil || *got[1].Feature != "Sub" || got[1].Project != "Alpha" {
		t.Fatalf("bad rows: %+v", got)
	}
	if _, err := New(Deps{Settings: fs{""}}).Folders(); errs.KindOf(err) != errs.KInvalid {
		t.Fatalf("no vault: %v", err)
	}
	if _, err := New(Deps{Settings: fs{filepath.Join(v, "nope")}}).Folders(); errs.KindOf(err) != errs.KInvalid {
		t.Fatalf("missing vault: %v", err)
	}
	empty := t.TempDir()
	if got, err := New(Deps{Settings: fs{empty}}).Folders(); err != nil || got == nil || len(got) != 0 {
		t.Fatalf("empty vault: %v %v", got, err)
	}
}

func TestPRD(t *testing.T) {
	v := mk(t, "05-Work/P/F", "05-Work/P/G")
	_ = os.WriteFile(filepath.Join(v, "05-Work/P/F/PRD.md"), []byte("# PRD - Login flow\n\n**Status:** Approved · 2026-01-01\n"), 0o644)
	_ = os.WriteFile(filepath.Join(v, "05-Work/P/G/PRD.md"), []byte("no heading\n**Status:** Draft"), 0o644)
	s := New(Deps{Settings: fs{v}})
	p, err := s.PRD("05-Work/P/F")
	if err != nil || !p.Exists || *p.Status != "Approved" || *p.Title != "Login flow" || p.Folder != "05-Work/P/F" {
		t.Fatalf("%+v %v", p, err)
	}
	p, _ = s.PRD("05-Work/P/G")
	if !p.Exists || *p.Status != "Draft" || p.Title != nil {
		t.Fatalf("%+v", p)
	}
	p, err = s.PRD("05-Work/P")
	if err != nil || p.Exists || p.Status != nil {
		t.Fatalf("%+v %v", p, err)
	}
	for _, bad := range []string{"", "05-Work/../x", "05-Work/.a", "elsewhere/P"} {
		if _, err := s.PRD(bad); errs.KindOf(err) != errs.KInvalid {
			t.Errorf("PRD(%q): %v", bad, err)
		}
	}
}

func TestParseSuggestion(t *testing.T) {
	for _, tc := range []struct {
		name, in string
		want     VaultSuggestion
		bad      bool
	}{
		{"plain", `{"project":"Acme","feature":"Login","new_project":false,"new_feature":true,"why":"fits"}`,
			VaultSuggestion{"Acme", "Login", false, true, "fits"}, false},
		{"fenced and chatty", "Sure!\n```json\n{\"project\":\"A/B\",\"feature\":\"C\\\\D\",\"new_project\":true,\"new_feature\":true,\"why\":\" x \"}\n```\nbye",
			VaultSuggestion{"A B", "C D", true, true, "x"}, false},
		{"braces in a string", `{"project":"P","feature":"F","why":"use {x} here"}`, VaultSuggestion{"P", "F", false, false, "use {x} here"}, false},
		{"first block invalid, second ok", `{nope} {"project":"P","feature":"F","why":""}`, VaultSuggestion{"P", "F", false, false, ""}, false},
		{"dot lead", `{"project":".git","feature":"F","why":""}`, VaultSuggestion{}, true},
		{"slash only", `{"project":"/","feature":"F","why":""}`, VaultSuggestion{}, true},
		{"empty feature", `{"project":"P","feature":"  ","why":""}`, VaultSuggestion{}, true},
		{"no json", `I think Acme`, VaultSuggestion{}, true},
		{"nul", "{\"project\":\"A\\u0000B\",\"feature\":\"F\",\"why\":\"\"}", VaultSuggestion{"A B", "F", false, false, ""}, false},
		{"long", `{"project":"` + strings.Repeat("p", 100) + `","feature":"F","why":"` + strings.Repeat("w", 300) + `"}`,
			VaultSuggestion{strings.Repeat("p", 80), "F", false, false, strings.Repeat("w", 200)}, false},
	} {
		got, err := ParseSuggestion(tc.in)
		if (err != nil) != tc.bad || got != tc.want {
			t.Errorf("%s: got %+v, %v", tc.name, got, err)
		}
	}
}

func TestSuggest(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	dir := t.TempDir()
	fakebin.Install(t, dir)
	v := mk(t, "05-Work/Acme/Login")
	reply := `{"project":"Acme","feature":"Billing","new_project":true,"new_feature":false,"why":"payments"}`
	fakebin.WriteRules(t, dir, []fakebin.Rule{{Bin: "claude", ArgsPrefix: []string{"-p", "--model", "haiku", "--output-format", "text"}, Stdout: reply}})
	s := New(Deps{Settings: fs{v}})
	got, err := s.Suggest(context.Background(), "add invoices")
	if err != nil {
		t.Fatal(err)
	}
	// flags follow the disk: Acme exists, Billing does not
	if got.Project != "Acme" || got.Feature != "Billing" || got.NewProject || !got.NewFeature || got.Why != "payments" {
		t.Fatalf("%+v", got)
	}
	calls := fakebin.Calls(t, dir)
	if len(calls) != 1 || calls[0].Cwd != realpath(v) && calls[0].Cwd != v {
		t.Fatalf("calls: %+v", calls)
	}
	prompt := calls[0].Args[len(calls[0].Args)-1]
	if !strings.Contains(prompt, "05-Work/Acme/Login") || !strings.Contains(prompt, "add invoices") {
		t.Fatalf("prompt: %s", prompt)
	}

	if _, err := s.Suggest(context.Background(), "  "); errs.KindOf(err) != errs.KInvalid {
		t.Fatalf("blank: %v", err)
	}
	fakebin.WriteRules(t, dir, []fakebin.Rule{{Bin: "claude", Stderr: "boom: not logged in\n", Exit: 1}})
	if _, err := s.Suggest(context.Background(), "x"); errs.KindOf(err) != errs.KUpstream || !strings.Contains(err.Error(), "not logged in") {
		t.Fatalf("exit 1: %v", err)
	}
	fakebin.WriteRules(t, dir, []fakebin.Rule{{Bin: "claude", Stdout: "no idea"}})
	if _, err := s.Suggest(context.Background(), "x"); errs.KindOf(err) != errs.KUpstream {
		t.Fatalf("garbage: %v", err)
	}
	// an empty vault lists "(none yet)"
	fakebin.WriteRules(t, dir, []fakebin.Rule{{Bin: "claude", Stdout: reply}})
	e := t.TempDir()
	if got, err := New(Deps{Settings: fs{e}}).Suggest(context.Background(), "x"); err != nil || !got.NewProject || !got.NewFeature {
		t.Fatalf("empty: %+v %v", got, err)
	}
	last := fakebin.Calls(t, dir)
	if p := last[len(last)-1].Args; !strings.Contains(p[len(p)-1], "(none yet)") {
		t.Fatalf("prompt: %s", p[len(p)-1])
	}
}

func realpath(p string) string { r, _ := filepath.EvalSymlinks(p); return r }

func TestRoutes(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	dir := t.TempDir()
	fakebin.Install(t, dir)
	fakebin.WriteRules(t, dir, []fakebin.Rule{{Bin: "claude", Stdout: `{"project":"P","feature":"F","why":"w"}`}})
	v := mk(t, "05-Work/P/F")
	os.WriteFile(filepath.Join(v, "05-Work/P/F/PRD.md"), []byte("# PRD - T\n**Status:** Draft"), 0o644)
	mux := http.NewServeMux()
	for _, r := range Routes(RouteDeps{Svc: New(Deps{Settings: fs{v}})}) {
		mux.Handle(r.Pattern, r.Handler)
	}
	do := func(method, path, body string) (int, map[string]any) {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		if body != "" {
			req.Header.Set("Content-Type", "application/json")
		}
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		var out map[string]any
		json.Unmarshal(rec.Body.Bytes(), &out)
		return rec.Code, out
	}
	code, out := do("GET", "/api/vault/folders", "")
	if code != 200 || out["vault"] != v || len(out["folders"].([]any)) != 2 {
		t.Fatalf("%d %v", code, out)
	}
	if code, out = do("GET", "/api/vault/prd?folder=05-Work/P/F", ""); code != 200 || out["exists"] != true || out["status"] != "Draft" || out["title"] != "T" {
		t.Fatalf("%d %v", code, out)
	}
	if code, _ = do("GET", "/api/vault/prd?folder=..", ""); code != 400 {
		t.Fatalf("%d", code)
	}
	if code, out = do("POST", "/api/vault/suggest", `{"text":"idea"}`); code != 200 || out["project"] != "P" || out["new_project"] != false {
		t.Fatalf("%d %v", code, out)
	}
	if code, _ = do("POST", "/api/vault/suggest", `{"text":""}`); code != 400 {
		t.Fatalf("%d", code)
	}
	fakebin.WriteRules(t, dir, []fakebin.Rule{{Bin: "claude", Stderr: "down", Exit: 2}})
	if code, _ = do("POST", "/api/vault/suggest", `{"text":"idea"}`); code != 502 {
		t.Fatalf("%d", code)
	}
	nov := http.NewServeMux()
	for _, r := range Routes(RouteDeps{Svc: New(Deps{Settings: fs{""}})}) {
		nov.Handle(r.Pattern, r.Handler)
	}
	rec := httptest.NewRecorder()
	nov.ServeHTTP(rec, httptest.NewRequest("GET", "/api/vault/folders", nil))
	if rec.Code != 400 {
		t.Fatalf("no vault: %d", rec.Code)
	}
}
