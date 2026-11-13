package prompts

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/blubird"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/home"
	builtin "github.com/masnun-siam/setu/prompts"
)

func env(t *testing.T) (*home.Home, string) {
	t.Helper()
	cfg := t.TempDir()
	t.Setenv("CLAUDE_CONFIG_DIR", cfg)
	t.Setenv("HOME", t.TempDir())
	t.Setenv("SETU_HOME", t.TempDir())
	h, err := home.Open()
	if err != nil {
		t.Fatal(err)
	}
	return h, cfg
}

func installBlubird(t *testing.T, cfg string) {
	t.Helper()
	inst := filepath.Join(cfg, "inst")
	_ = os.MkdirAll(inst, 0o755)
	p := filepath.Join(cfg, "plugins")
	_ = os.MkdirAll(p, 0o755)
	_ = os.WriteFile(filepath.Join(p, "installed_plugins.json"),
		[]byte(`{"plugins":{"blubird@agentic-workflow":[{"scope":"user","installPath":"`+inst+`","version":"1"}]}}`), 0o644)
}

func load(t *testing.T, withBlubird bool) *Registry {
	h, cfg := env(t)
	if withBlubird {
		installBlubird(t, cfg)
	}
	r, err := Load(h, "1.0.0", blubird.New(h, events.New()))
	if err != nil {
		t.Fatal(err)
	}
	return r
}

func TestRegistryCoversSpec(t *testing.T) {
	r := load(t, false)
	want := strings.Fields("create-prd map-prds create-tasks small-change refine-issues reproduce-bug implement-issue after-merge verifier-locally project-coordinator pr-review peer-review pr-grind release-pr release-note agentic-onboard ci-optimize security-sweep docs-updater skill-feedback day-end-reconcile weekly-review")
	got := r.Steps()
	if len(got) != len(want) {
		t.Fatalf("%d steps, want %d", len(got), len(want))
	}
	for i, s := range got {
		if s.ID != want[i] {
			t.Fatalf("step %d = %s, want %s", i, s.ID, want[i])
		}
		if s.Label == "" || s.Stage == "" || s.Skill == "" {
			t.Fatalf("incomplete %+v", s)
		}
	}
	for _, id := range []string{"peer-review", "pr-grind", "release-pr", "release-note"} {
		if s, _ := r.Step(id); s.Source != SrcSetu {
			t.Fatalf("%s source %s", id, s.Source)
		}
	}
	if s, _ := r.Step("small-change"); s.Skill != "create-tasks" || s.RunsIn != InRepo {
		t.Fatalf("%+v", s)
	}
	if s, _ := r.Step("map-prds"); !s.InStage("ops") || !s.InStage("prd") || s.InStage("me") {
		t.Fatalf("%+v", s)
	}
}

func TestBuildShapes(t *testing.T) {
	r := load(t, true)
	p, err := r.Build("implement-issue", "  12 ")
	if err != nil || p.Display != "/blubird:implement-issue 12" || p.Text != p.Display || p.Step != "implement-issue" {
		t.Fatalf("%+v %v", p, err)
	}
	if p, _ = r.Build("day-end-reconcile", ""); p.Text != "/blubird:day-end-reconcile" {
		t.Fatalf("%q", p.Text)
	}
	p, err = r.Build("release-pr", "--dry-run")
	if err != nil {
		t.Fatal(err)
	}
	if p.Display != "/release-pr --dry-run" {
		t.Fatalf("display %q", p.Display)
	}
	if !strings.HasPrefix(p.Text, "Base directory for this skill: "+r.Root()+"/release-pr\n\n") {
		t.Fatalf("text head %q", p.Text[:120])
	}
	if !strings.HasSuffix(p.Text, "\n\nARGUMENTS: --dry-run") {
		t.Fatalf("text tail %q", p.Text[len(p.Text)-60:])
	}
	if strings.Contains(p.Text, "name: release-pr") || strings.Contains(p.Text, "\n---\nname") {
		t.Fatal("frontmatter not stripped")
	}
	if p, _ = r.Build("release-note", ""); !strings.HasSuffix(p.Text, "ARGUMENTS:") {
		t.Fatalf("empty args tail %q", p.Text[len(p.Text)-30:])
	}
}

func TestArgChecks(t *testing.T) {
	r := load(t, true)
	atCap, overCap := strings.Repeat("x", MaxArgChars), strings.Repeat("x", MaxArgChars+1)
	cases := []struct {
		step, args, repo string
		ok               bool
		want             string // expected args in Display
	}{
		{"implement-issue", "12", "", true, "12"},
		{"implement-issue", "#12 extra words", "", true, "#12 extra words"},
		{"implement-issue", "https://github.com/o/r/issues/3", "", true, ""},
		{"implement-issue", "", "", false, ""},
		{"implement-issue", "fix it", "", false, ""},
		{"after-merge", "7 (PR #8 for issue #7 is merged: run the follow-ups)", "", true, ""},
		{"after-merge", "https://github.com/o/r/issues/3", "", false, ""},
		{"refine-issues", "#4, 5 6", "", true, "4 5 6"},
		{"refine-issues", "epic", "", false, ""},
		{"pr-grind", "https://github.com/o/r/pull/9 --channel C123 --reviewer copilot", "", true, ""},
		{"pr-grind", "9", "o/r", true, "https://github.com/o/r/pull/9"},
		{"pr-grind", "#9 --mode simple", "o/r", true, "https://github.com/o/r/pull/9 --mode simple"},
		{"pr-grind", "9", "", false, ""},
		{"pr-grind", "http://x/y", "", false, ""},
		{"pr-grind", "https://github.com/o/r/pull/9 --channel", "", false, ""},
		{"pr-grind", "https://github.com/o/r/pull/9 --bogus x", "", false, ""},
		{"pr-grind", "https://github.com/o/r/pull/9 --reviewer a/b", "", false, ""},
		{"create-tasks", "docs/prds/billing/invoices.md", "", true, ""},
		{"create-tasks", "/abs/repo/docs/prds/x.md", "", true, ""},
		{"create-tasks", "docs/other/x.md", "", false, ""},
		{"create-tasks", "docs/prds/../x.md", "", false, ""},
		{"create-tasks", "docs/prds/x.txt", "", false, ""},
		{"release-pr", "--dry-run staging master", "", true, ""},
		{"release-note", "--draft /tmp/x https://github.com/o/r/pull/1", "", true, ""},
		{"peer-review", "--root p-20260101T000000Z-abcdef /tmp/a.md", "", true, ""},
		{"pr-review", "--fix 12", "", true, ""},
		{"project-coordinator", "--max 3", "", true, ""},
		{"agentic-onboard", "--dev", "", true, ""},
		{"docs-updater", "--full", "", false, ""},
		{"small-change", "-rf", "", false, ""},
		{"small-change", "Fix the export\n\nPriority: P2", "", true, "Fix the export\n\nPriority: P2"},
		{"small-change", "a\r\nb", "", true, "a\nb"},
		{"small-change", "a\rb", "", true, "a\nb"},
		{"small-change", atCap, "", true, atCap},
		{"small-change", overCap, "", false, ""},
		{"small-change", "  " + strings.Repeat("é", MaxArgChars) + "\n", "", true, ""},
		{"small-change", strings.Repeat("x", MaxArgChars-1) + "\r\n", "", true, ""},
		{"small-change", strings.Repeat("x", MaxArgChars-2) + "\r\ny", "", true, ""},
		{"small-change", "-a\nb", "", false, ""},
		{"implement-issue", "1 " + strings.Repeat("x", MaxArgChars-2), "", true, ""},
		{"implement-issue", "1 " + strings.Repeat("x", MaxArgChars-1), "", false, ""},
		{"implement-issue", "12\nmore", "", false, ""},
		{"refine-issues", "4\n5", "", false, ""},
		{"create-prd", "an idea\nover two lines", "", false, ""},
		{"create-prd", "an idea\rover two lines", "", false, ""},
		{"small-change", "bad\x00nul", "", false, ""},
		{"nope", "", "", false, ""},
	}
	for _, c := range cases {
		p, err := r.BuildIn(c.step, c.args, c.repo)
		if (err == nil) != c.ok {
			t.Errorf("%s %q: err=%v want ok=%v", c.step, c.args, err, c.ok)
			continue
		}
		if err != nil {
			if k := errs.KindOf(err); k != errs.KInvalid && c.step != "nope" {
				t.Errorf("%s %q: kind %v", c.step, c.args, k)
			}
			continue
		}
		if c.want != "" && !strings.HasSuffix(p.Display, " "+c.want) {
			t.Errorf("%s %q: display %q want args %q", c.step, c.args, p.Display, c.want)
		}
	}
	if k := errs.KindOf(func() error { _, e := r.Build("nope", ""); return e }()); k != errs.KNotFound {
		t.Errorf("unknown step kind %v", k)
	}
}

// report-bug is keyed by step id; the step itself is registered elsewhere, so check its args directly.
func TestArgChecksReportBugMultiLine(t *testing.T) {
	lines := make([]string, 40)
	for i := range lines {
		lines[i] = fmt.Sprintf("\tat frame%d (main.go:%d)", i, i+1)
	}
	a := strings.Join(lines, "\r\n")
	if err := checkArgs(Step{ID: "report-bug"}, &a, ""); err != nil {
		t.Fatalf("40-line report-bug arg: %v", err)
	}
	if n := len(strings.Split(a, "\n")); n != 40 || strings.Contains(a, "\r") {
		t.Errorf("report-bug arg has %d lines, \\r left: %v", n, strings.Contains(a, "\r"))
	}
	bad := "trace\x00here"
	if err := checkArgs(Step{ID: "report-bug"}, &bad, ""); errs.KindOf(err) != errs.KInvalid {
		t.Errorf("NUL in report-bug: err %v", err)
	}
	long := strings.Repeat("y", MaxArgChars+1)
	if err := checkArgs(Step{ID: "report-bug"}, &long, ""); errs.KindOf(err) != errs.KInvalid {
		t.Errorf("over-cap report-bug: err %v", err)
	}
}

func TestIssueOf(t *testing.T) {
	for _, c := range []struct {
		step, args string
		n          int
		ok         bool
	}{
		{"implement-issue", "12", 12, true}, {"after-merge", "#7 (PR…)", 7, true},
		{"implement-issue", "https://x/y", 0, false}, {"refine-issues", "3", 0, false}, {"implement-issue", "", 0, false},
	} {
		if n, ok := IssueOf(c.step, c.args); n != c.n || ok != c.ok {
			t.Errorf("%v: %d %v", c, n, ok)
		}
	}
}

func TestAvailable(t *testing.T) {
	r := load(t, false)
	if err := r.Available("pr-grind"); err != nil {
		t.Fatal(err)
	}
	err := r.Available("implement-issue")
	if errs.KindOf(err) != errs.KConflict || err.Error() != "blubird is not installed" || errs.Status(err) != 409 {
		t.Fatalf("%v", err)
	}
	if errs.KindOf(r.Available("zzz")) != errs.KNotFound {
		t.Fatal("unknown step")
	}
	if err := load(t, true).Available("implement-issue"); err != nil {
		t.Fatal(err)
	}
}

func TestAgents(t *testing.T) {
	r := load(t, false)
	body, tools, err := r.Agent("peer-reviewer")
	if err != nil || !strings.HasPrefix(body, "You are a **single-lens reviewer**") || strings.Contains(body, "tools:") {
		t.Fatalf("%v %.60q", err, body)
	}
	if len(tools) != 14 || tools[0] != "Read" || tools[3] != "Bash(gh pr view:*)" {
		t.Fatalf("tools %q", tools)
	}
	body, tools, err = r.Agent("away-answerer")
	if err != nil || !strings.Contains(body, "AWAY-ANSWER:") || len(tools) != 11 {
		t.Fatalf("%v %d", err, len(tools))
	}
	if _, _, err := r.Agent("x"); errs.KindOf(err) != errs.KNotFound {
		t.Fatal("unknown agent")
	}
}

func TestExtractionIdempotentAndExecutable(t *testing.T) {
	h, _ := env(t)
	r, err := Load(h, "9.9.9", nil)
	if err != nil {
		t.Fatal(err)
	}
	if r.Root() != h.Path("prompts", "9.9.9") {
		t.Fatalf("root %s", r.Root())
	}
	sh := filepath.Join(r.Root(), "release-pr", "scripts", "release-data.sh")
	fi, err := os.Stat(sh)
	if err != nil || fi.Mode()&0o111 == 0 {
		t.Fatalf("script %v %v", err, fi)
	}
	for _, f := range []string{"pr-grind/SKILL.md", "release-note/SKILL.md", "peer-review/SKILL.md", "agents/peer-reviewer.md", "agents/away-answerer.md"} {
		if _, err := os.Stat(filepath.Join(r.Root(), f)); err != nil {
			t.Fatal(err)
		}
	}
	old := time.Now().Add(-time.Hour)
	_ = os.Chtimes(sh, old, old)
	if _, err := Load(h, "9.9.9", nil); err != nil {
		t.Fatal(err)
	}
	if fi2, _ := os.Stat(sh); !fi2.ModTime().Equal(fi.ModTime()) && !fi2.ModTime().Equal(old) {
		t.Fatal("second Load rewrote the files")
	}
	if fi2, _ := os.Stat(sh); !fi2.ModTime().Equal(old) {
		t.Fatal("second Load rewrote the files")
	}
	// a damaged extraction is repaired
	_ = os.WriteFile(filepath.Join(r.Root(), ".extracted"), []byte("stale\n"), 0o644)
	_ = os.WriteFile(filepath.Join(r.Root(), "pr-grind", "SKILL.md"), []byte("broken"), 0o644)
	if _, err := Load(h, "9.9.9", nil); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(filepath.Join(r.Root(), "pr-grind", "SKILL.md"))
	if !strings.Contains(string(b), "name: pr-grind") {
		t.Fatal("not repaired")
	}
}

func TestPruneKeepsFiveAndCurrent(t *testing.T) {
	h, _ := env(t)
	base := h.Path("prompts")
	for i, v := range []string{"0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7"} {
		d := filepath.Join(base, v)
		_ = os.MkdirAll(d, 0o755)
		ts := time.Now().Add(time.Duration(i-100) * time.Hour)
		_ = os.Chtimes(d, ts, ts)
	}
	if _, err := Load(h, "0.1", nil); err != nil { // current version is the oldest on disk
		t.Fatal(err)
	}
	ents, _ := os.ReadDir(base)
	var names []string
	for _, e := range ents {
		names = append(names, e.Name())
	}
	if len(names) != 5 {
		t.Fatalf("kept %v", names)
	}
	have := map[string]bool{}
	for _, n := range names {
		have[n] = true
	}
	for _, v := range []string{"0.1", "0.7", "0.6", "0.5", "0.4"} {
		if !have[v] {
			t.Fatalf("lost %s, kept %v", v, names)
		}
	}
}

func TestVersionSanitised(t *testing.T) {
	h, _ := env(t)
	r, err := Load(h, "../evil", nil)
	if err != nil || r.Root() != h.Path("prompts", "dev") {
		t.Fatalf("%v %v", r, err)
	}
}

// The embedded prompts must be self-contained: no aiw, no plugin-relative paths, no user paths,
// every setu verb they call exists in API.md §8.
func TestEmbeddedContent(t *testing.T) {
	banned := []string{"aiw ", "aiw\n", "`aiw", "AIW_", "ai-workflow", "../../", "self-improve", "/Users/", "CLAUDE_PLUGIN", "ScheduleWakeup({"}
	var n int
	err := fs.WalkDir(builtin.FS, ".", func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || strings.HasSuffix(p, ".go") {
			return err
		}
		b, _ := fs.ReadFile(builtin.FS, p)
		n++
		for _, w := range banned {
			if strings.Contains(string(b), w) {
				t.Errorf("%s contains %q", p, w)
			}
		}
		return nil
	})
	if err != nil || n < 7 {
		t.Fatalf("walked %d files, err %v", n, err)
	}
	verbs := map[string]bool{"paths": true, "ask": true, "ci": true, "threads": true, "grind": true, "jev": true, "review": true, "blubird": true, "dispatch": true, "timer": true}
	grind := map[string]bool{"start": true, "wait": true, "ci": true, "threads": true, "retrigger": true, "record": true, "pause": true, "done": true, "status": true, "mode": true, "reviewers": true}
	for _, f := range []string{"release-pr", "pr-grind", "release-note", "peer-review"} {
		b, _ := fs.ReadFile(builtin.FS, f+"/SKILL.md")
		var code strings.Builder
		for _, m := range regexp.MustCompile("(?s)```.*?```|`[^`\\n]+`").FindAllString(string(b), -1) {
			code.WriteString(m + "\n")
		}
		for _, m := range regexp.MustCompile(`\bsetu ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?`).FindAllStringSubmatch(code.String(), -1) {
			if !verbs[m[1]] {
				t.Errorf("%s: unknown verb setu %s", f, m[1])
			}
			if m[1] == "grind" && m[2] != "" && !grind[m[2]] {
				t.Errorf("%s: unknown grind verb %q", f, m[2])
			}
		}
	}
}

func TestPromptFixedTexts(t *testing.T) {
	if !strings.Contains(Headless, "setu ask --json") || strings.Contains(Headless, "aiw") {
		t.Fatal(Headless)
	}
	if !strings.Contains(Reentry, "setu timer") || !strings.Contains(Reentry, "`setu ask`") || strings.Contains(Reentry, "aiw") {
		t.Fatal(Reentry)
	}
}
