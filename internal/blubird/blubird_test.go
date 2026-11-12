package blubird

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

func write(t *testing.T, p, s string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(s), 0o644); err != nil {
		t.Fatal(err)
	}
}

// setup points CLAUDE_CONFIG_DIR at a temp dir with blubird installed (or not).
func setup(t *testing.T, installed bool) (cfg, install string) {
	t.Helper()
	cfg = t.TempDir()
	t.Setenv("CLAUDE_CONFIG_DIR", cfg)
	t.Setenv("HOME", t.TempDir())
	t.Setenv("SETU_HOME", t.TempDir())
	install = filepath.Join(cfg, "plugins", "cache", "agentic-workflow", "blubird", "1.2.0")
	mk := filepath.Join(cfg, "plugins", "marketplaces", "agentic-workflow")
	write(t, filepath.Join(mk, ".claude-plugin", "marketplace.json"),
		`{"plugins":[{"name":"blubird","version":"1.3.0","source":"./plugins/blubird"}]}`)
	write(t, filepath.Join(cfg, "plugins", "known_marketplaces.json"),
		`{"agentic-workflow":{"installLocation":`+jstr(mk)+`}}`)
	if installed {
		write(t, filepath.Join(install, "skills", "implement-issue", "SKILL.md"), "x")
		write(t, filepath.Join(install, "skills", "nodoc", "README.md"), "x")
		write(t, filepath.Join(install, "hooks", "hooks.json"), `{"hooks":{"UserPromptSubmit":[],"PreToolUse":[]}}`)
		write(t, filepath.Join(cfg, "plugins", "installed_plugins.json"),
			`{"version":2,"plugins":{"other@x":[{"scope":"user","installPath":"/nope","version":"9"}],
			"blubird@agentic-workflow":[{"scope":"user","installPath":`+jstr(install)+`,"version":"1.2.0"}]}}`)
	}
	return cfg, install
}

func jstr(s string) string { b, _ := json.Marshal(s); return string(b) }

func newMgr(t *testing.T) *Manager {
	h, err := home.Open()
	if err != nil {
		t.Fatal(err)
	}
	return New(h, events.New())
}

func TestDetect(t *testing.T) {
	_, install := setup(t, true)
	st := newMgr(t).Status()
	if !st.Installed || st.Version != "1.2.0" || st.InstallPath != install || st.Latest != "1.3.0" || !st.UpdateAvailable {
		t.Fatalf("status %+v", st)
	}
	if st.Marketplace != "agentic-workflow" || len(st.Skills) != 1 || st.Skills[0] != "implement-issue" {
		t.Fatalf("skills/marketplace %+v", st)
	}
	if len(st.Hooks) != 2 || st.Hooks[0] != "PreToolUse" {
		t.Fatalf("hooks %v", st.Hooks)
	}
	m := newMgr(t)
	if d, ok := m.SkillDir("implement-issue"); !ok || d != filepath.Join(install, "skills", "implement-issue") {
		t.Fatalf("SkillDir %q %v", d, ok)
	}
	if _, ok := m.SkillDir("../x"); ok {
		t.Fatal("traversal accepted")
	}
	if _, ok := m.SkillDir("nodoc"); ok {
		t.Fatal("dir without SKILL.md accepted")
	}
}

func TestMissing(t *testing.T) {
	setup(t, false)
	m := newMgr(t)
	st := m.Status()
	if st.Installed || st.UpdateAvailable || st.Version != "" || st.Skills == nil {
		t.Fatalf("status %+v", st)
	}
	if _, ok := m.SkillDir("create-prd"); ok {
		t.Fatal("skill dir for missing plugin")
	}
	b, _ := json.Marshal(st)
	if !strings.Contains(string(b), `"skills":[]`) {
		t.Fatalf("json %s", b)
	}
}

func TestStaleInstallPathIsMissing(t *testing.T) {
	cfg, _ := setup(t, false)
	write(t, filepath.Join(cfg, "plugins", "installed_plugins.json"),
		`{"plugins":{"blubird@agentic-workflow":[{"scope":"user","installPath":"/does/not/exist","version":"1"}]}}`)
	if newMgr(t).Status().Installed {
		t.Fatal("stale record counted as installed")
	}
}

func TestRedetectOnMtime(t *testing.T) {
	cfg, install := setup(t, false)
	m := newMgr(t)
	if m.Status().Installed {
		t.Fatal("installed")
	}
	write(t, filepath.Join(install, "skills", "a", "SKILL.md"), "x")
	p := filepath.Join(cfg, "plugins", "installed_plugins.json")
	write(t, p, `{"plugins":{"blubird@agentic-workflow":[{"scope":"user","installPath":`+jstr(install)+`,"version":"1.2.0"}]}}`)
	future := time.Now().Add(time.Hour)
	_ = os.Chtimes(p, future, future)
	if !m.Status().Installed {
		t.Fatal("not re-detected")
	}
}

func TestDefaultConfigDir(t *testing.T) {
	hd := t.TempDir()
	t.Setenv("CLAUDE_CONFIG_DIR", "")
	t.Setenv("HOME", hd)
	t.Setenv("SETU_HOME", t.TempDir())
	install := filepath.Join(hd, "inst")
	write(t, filepath.Join(install, "skills", "x", "SKILL.md"), "x")
	write(t, filepath.Join(hd, ".claude", "plugins", "installed_plugins.json"),
		`{"plugins":{"blubird@agentic-workflow":[{"scope":"user","installPath":`+jstr(install)+`,"version":"2"}]}}`)
	if st := newMgr(t).Status(); !st.Installed || st.Version != "2" {
		t.Fatalf("%+v", st)
	}
}

func rules(t *testing.T, dir string, r ...fakebin.Rule) {
	t.Helper()
	fakebin.WriteRules(t, dir, r)
}

func claudeArgs(t *testing.T, dir string) []string {
	var out []string
	for _, c := range fakebin.Calls(t, dir) {
		if c.Bin == "claude" {
			out = append(out, strings.Join(c.Args, " "))
		}
	}
	return out
}

func TestInstallSequence(t *testing.T) {
	setup(t, false)
	bin := t.TempDir()
	fakebin.Install(t, bin)
	rules(t, bin, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"plugin"}, Stdout: "ok"})
	m := newMgr(t)
	sub, cancel := m.bus.Subscribe(16)
	defer cancel()
	if err := m.Install(context.Background()); err != nil {
		t.Fatal(err)
	}
	m.Wait()
	got := claudeArgs(t, bin)
	want := []string{"plugin marketplace add blubird-interactiveltd/agentic-workflow", "plugin install blubird@agentic-workflow"}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("argv %v", got)
	}
	if st := m.Status(); st.Busy != "" || st.Error != "" {
		t.Fatalf("%+v", st)
	}
	var kinds []string
	for len(sub) > 0 {
		ev := <-sub
		kinds = append(kinds, string(ev.Topic))
	}
	if strings.Join(kinds, ",") != "products,products,toast" {
		t.Fatalf("events %v", kinds)
	}
}

func TestInstallToleratesAlreadyAddedAndFailsOnInstall(t *testing.T) {
	setup(t, false)
	bin := t.TempDir()
	fakebin.Install(t, bin)
	rules(t, bin,
		fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"plugin", "marketplace", "add"}, Stderr: "Marketplace already added", Exit: 1},
		fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"plugin", "install"}, Stderr: "boom", Exit: 2})
	m := newMgr(t)
	if err := m.Install(context.Background()); err != nil {
		t.Fatal(err)
	}
	m.Wait()
	st := m.Status()
	if !strings.Contains(st.Error, "plugin install blubird@agentic-workflow: boom") {
		t.Fatalf("error %q", st.Error)
	}
	if len(claudeArgs(t, bin)) != 2 {
		t.Fatalf("calls %v", claudeArgs(t, bin))
	}
}

func TestUpdateSequenceAndUnknownCommand(t *testing.T) {
	setup(t, false)
	bin := t.TempDir()
	fakebin.Install(t, bin)
	rules(t, bin,
		fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"plugin", "marketplace", "update"}},
		fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"plugin", "update"}, Stderr: "error: unknown command 'update'", Exit: 1})
	m := newMgr(t)
	if err := m.Update(context.Background()); err != nil {
		t.Fatal(err)
	}
	m.Wait()
	if st := m.Status(); st.Error != "" {
		t.Fatalf("unknown command should be success: %q", st.Error)
	}
	got := strings.Join(claudeArgs(t, bin), "|")
	if got != "plugin marketplace update agentic-workflow|plugin update blubird@agentic-workflow" {
		t.Fatalf("argv %s", got)
	}
}

func TestMarketplaceUpdateFailureIsReported(t *testing.T) {
	setup(t, false)
	bin := t.TempDir()
	fakebin.Install(t, bin)
	rules(t, bin, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"plugin"}, Stderr: "network down", Exit: 1})
	m := newMgr(t)
	_ = m.Update(context.Background())
	m.Wait()
	if st := m.Status(); !strings.Contains(st.Error, "network down") {
		t.Fatalf("%q", st.Error)
	}
	if n := len(claudeArgs(t, bin)); n != 1 {
		t.Fatalf("a failed step must stop the sequence, calls=%d", n)
	}
}

func TestBusyIsConflict(t *testing.T) {
	setup(t, false)
	bin := t.TempDir()
	fakebin.Install(t, bin)
	rules(t, bin, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"plugin"}, SleepMs: 300})
	m := newMgr(t)
	if err := m.Install(context.Background()); err != nil {
		t.Fatal(err)
	}
	if st := m.Status(); st.Busy != "installing" {
		t.Fatalf("busy %q", st.Busy)
	}
	err := m.Update(context.Background())
	if errs.KindOf(err) != errs.KConflict || errs.Status(err) != 409 {
		t.Fatalf("err %v", err)
	}
	m.Wait()
}

func TestClaudeMissingIsUpstream(t *testing.T) {
	setup(t, false)
	t.Setenv("PATH", t.TempDir())
	err := newMgr(t).Install(context.Background())
	if errs.KindOf(err) != errs.KUpstream || errs.Status(err) != 502 {
		t.Fatalf("err %v", err)
	}
}
