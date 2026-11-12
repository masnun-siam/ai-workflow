package home

import (
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

func newHome(t *testing.T) *Home {
	t.Helper()
	t.Setenv("HOME", t.TempDir())
	t.Setenv("SETU_HOME", filepath.Join(t.TempDir(), "setu"))
	h, err := Open()
	if err != nil {
		t.Fatal(err)
	}
	return h
}

func write(t *testing.T, p, s string, mode os.FileMode) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(s), mode); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(p, mode); err != nil {
		t.Fatal(err)
	}
}

func TestOpenAndPath(t *testing.T) {
	h := newHome(t)
	if st, err := os.Stat(h.Root); err != nil || st.Mode().Perm() != 0o700 {
		t.Fatalf("%v %v", st, err)
	}
	if h.Path("a", "b.json") != filepath.Join(h.Root, "a", "b.json") {
		t.Fatal(h.Path("a", "b.json"))
	}
	t.Setenv("SETU_HOME", "")
	t.Setenv("HOME", t.TempDir())
	h2, err := Open()
	if err != nil || filepath.Base(h2.Root) != ".setu" {
		t.Fatalf("%v %v", h2, err)
	}
}

func TestOldDataDir(t *testing.T) {
	t.Setenv("HOME", "/h")
	t.Setenv("CLAUDE_PLUGIN_DATA", "")
	if OldDataDir() != "/h/.claude/plugins/data/ai-workflow" {
		t.Fatal(OldDataDir())
	}
	t.Setenv("CLAUDE_PLUGIN_DATA", "/x")
	if OldDataDir() != "/x" {
		t.Fatal(OldDataDir())
	}
}

func TestMigrate(t *testing.T) {
	h := newHome(t)
	old := t.TempDir()
	write(t, filepath.Join(old, "ui_settings.json"), `{"a":1}`, 0o644)
	write(t, filepath.Join(old, "ui.json"), `{"ntfy":{}}`, 0o600)
	write(t, filepath.Join(old, "sessions", "s1", "meta.json"), `{}`, 0o644)
	write(t, filepath.Join(old, "sessions", "s1", "stream.jsonl"), strings.Repeat("x", 3<<20), 0o644)
	write(t, filepath.Join(old, "sessions", "s1", ".lock"), "", 0o644)
	write(t, filepath.Join(old, "ui_settings.json.lock"), "", 0o644)
	if err := os.Symlink("ui.json", filepath.Join(old, "link")); err != nil {
		t.Fatal(err)
	}
	sock := filepath.Join(old, "s.sock")
	if l, err := net.Listen("unix", sock); err == nil {
		defer l.Close()
	}

	copied, err := Migrate(h, old)
	if err != nil || !copied {
		t.Fatalf("copied=%v err=%v", copied, err)
	}
	if st, err := os.Stat(h.Path("ui.json")); err != nil || st.Mode().Perm() != 0o600 {
		t.Fatalf("ui.json mode: %v %v", st, err)
	}
	if b, _ := os.ReadFile(h.Path("sessions", "s1", "stream.jsonl")); len(b) != 3<<20 {
		t.Fatal("stream not copied fully")
	}
	for _, skip := range []string{"sessions/s1/.lock", "ui_settings.json.lock", "s.sock"} {
		if _, err := os.Lstat(h.Path(skip)); err == nil {
			t.Errorf("%s should be skipped", skip)
		}
	}
	if l, err := os.Readlink(h.Path("link")); err != nil || l != "ui.json" {
		t.Errorf("symlink: %q %v", l, err)
	}
	if _, err := os.Stat(h.Path(".migrated")); err != nil {
		t.Fatal("no marker")
	}
	if _, err := os.Stat(filepath.Join(old, "sessions", "s1", "meta.json")); err != nil {
		t.Fatal("old dir was touched")
	}
	// idempotent: later changes in old are not copied again; local edits survive
	write(t, h.Path("ui_settings.json"), `{"a":2}`, 0o644)
	write(t, filepath.Join(old, "new.json"), `{}`, 0o644)
	if copied, err := Migrate(h, old); copied || err != nil {
		t.Fatalf("second run: %v %v", copied, err)
	}
	if b, _ := os.ReadFile(h.Path("ui_settings.json")); string(b) != `{"a":2}` {
		t.Fatal("overwritten")
	}
	if _, err := os.Stat(h.Path("new.json")); err == nil {
		t.Fatal("copied twice")
	}
}

func TestMigrateMissingOld(t *testing.T) {
	h := newHome(t)
	copied, err := Migrate(h, filepath.Join(t.TempDir(), "nope"))
	if copied || err != nil {
		t.Fatalf("%v %v", copied, err)
	}
	if _, err := os.Stat(h.Path(".migrated")); err != nil {
		t.Fatal("marker expected")
	}
}

func TestMigrateRefusesNesting(t *testing.T) {
	h := newHome(t)
	if _, err := Migrate(h, filepath.Dir(h.Root)); err == nil {
		t.Fatal("expected error for home inside old")
	}
}

func TestJSONHelpers(t *testing.T) {
	h := newHome(t)
	type doc struct {
		N int      `json:"n"`
		S []string `json:"s"`
	}
	p := h.Path("d.json")
	d := doc{N: 5}
	if err := ReadJSON(p, &d); err != nil || d.N != 5 {
		t.Fatalf("missing file: %v %+v", err, d)
	}
	if err := WriteJSON(p, doc{N: 1, S: []string{"a"}}); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(p)
	if string(b) != "{\n  \"n\": 1,\n  \"s\": [\n    \"a\"\n  ]\n}\n" {
		t.Fatalf("%q", b)
	}
	write(t, p, "{broken", 0o644)
	d = doc{N: 9}
	if err := ReadJSON(p, &d); err != nil || d.N != 9 {
		t.Fatalf("corrupt: %v %+v", err, d)
	}
	write(t, p, "", 0o644)
	if err := ReadJSON(p, &d); err != nil || d.N != 9 {
		t.Fatalf("empty: %v %+v", err, d)
	}
	for _, name := range []string{"ui.json", "push.json"} {
		if err := WriteJSON(h.Path(name), d); err != nil {
			t.Fatal(err)
		}
		if st, _ := os.Stat(h.Path(name)); st.Mode().Perm() != 0o600 {
			t.Errorf("%s mode %v", name, st.Mode())
		}
	}
}

func TestCorruptBackup(t *testing.T) {
	h := newHome(t)
	p := h.Path("c.json")
	write(t, p, "{nope", 0o644)
	type doc struct{ N int }
	v, err := UpdateJSON(p, func(d *doc) error { d.N++; return nil })
	if err != nil || v.N != 1 {
		t.Fatalf("%v %+v", err, v)
	}
	matches, _ := filepath.Glob(p + ".corrupt-*")
	if len(matches) != 1 {
		t.Fatalf("backups: %v", matches)
	}
	if b, _ := os.ReadFile(matches[0]); string(b) != "{nope" {
		t.Fatal("backup content")
	}
}

type counter struct{ N int }

func TestUpdateJSONContention(t *testing.T) {
	if os.Getenv("HOME_TEST_CHILD") == "inc" {
		p := os.Getenv("HOME_TEST_FILE")
		for i := 0; i < 50; i++ {
			if _, err := UpdateJSON(p, func(c *counter) error { c.N++; return nil }); err != nil {
				os.Exit(3)
			}
		}
		os.Exit(0)
	}
	h := newHome(t)
	p := h.Path("n.json")
	cmd := exec.Command(os.Args[0], "-test.run=^TestUpdateJSONContention$")
	cmd.Env = append(os.Environ(), "HOME_TEST_CHILD=inc", "HOME_TEST_FILE="+p)
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	for g := 0; g < 2; g++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < 50; i++ {
				if _, err := UpdateJSON(p, func(c *counter) error { c.N++; return nil }); err != nil {
					t.Error(err)
					return
				}
			}
		}()
	}
	wg.Wait()
	if err := cmd.Wait(); err != nil {
		t.Fatal(err)
	}
	var c counter
	if err := ReadJSON(p, &c); err != nil || c.N != 150 {
		t.Fatalf("lost writes: %d %v", c.N, err)
	}
}

func TestTryLockHeldByChild(t *testing.T) {
	h := newHome(t)
	p := h.Path("l.json")
	f, ok, err := TryLock(p)
	if err != nil || !ok {
		t.Fatalf("%v %v", ok, err)
	}
	if _, ok2, _ := TryLock(p); ok2 {
		t.Fatal("second TryLock must fail while held")
	}
	child := exec.Command("sleep", "30")
	child.ExtraFiles = []*os.File{f}
	if err := child.Start(); err != nil {
		t.Fatal(err)
	}
	f.Close() // the parent lets go; the child's inherited fd still holds the lock
	if g, ok, _ := TryLock(p); ok {
		g.Close()
		t.Fatal("child fd should hold the lock")
	}
	unlockDone := make(chan struct{})
	go func() { // a blocking Lock waits for the child
		un, err := Lock(p)
		if err == nil {
			un()
		}
		close(unlockDone)
	}()
	select {
	case <-unlockDone:
		t.Fatal("Lock should block")
	case <-time.After(200 * time.Millisecond):
	}
	_ = child.Process.Kill()
	_ = child.Wait()
	select {
	case <-unlockDone:
	case <-time.After(3 * time.Second):
		t.Fatal("Lock did not unblock")
	}
	g, ok, err := TryLock(p)
	if err != nil || !ok {
		t.Fatalf("after kill: %v %v", ok, err)
	}
	g.Close()
	_ = strconv.Itoa
}
