// Package e2e builds the setu binary, runs `setu serve` on a free port against a temp SETU_HOME
// and HOME with fake claude/gh binaries on PATH, and drives the HTTP API.
package e2e

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

type obj = map[string]any

type server struct {
	t    *testing.T
	base string
	fb   string // fakebin dir
	home string // SETU_HOME
	hm   string // HOME
	cmd  *exec.Cmd
	log  *bytes.Buffer

	mu     sync.Mutex
	events []string // "topic data" lines of the SSE stream
}

func freePort(t *testing.T) int {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

func buildBinary(t *testing.T) string {
	dir := t.TempDir()
	bin := filepath.Join(dir, "setu")
	c := exec.Command("go", "build", "-o", bin, "../cmd/setu")
	if out, err := c.CombinedOutput(); err != nil {
		t.Fatalf("go build: %v\n%s", err, out)
	}
	return bin
}

func write(t *testing.T, path, content string) string {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func jl(evs ...obj) string {
	var b strings.Builder
	for _, e := range evs {
		x, _ := json.Marshal(e)
		b.Write(x)
		b.WriteByte('\n')
	}
	return b.String()
}

const askQ = `{"questions":[{"header":"Pick","question":"Which?","multiSelect":false,"options":[{"label":"A (Recommended)","description":"first"},{"label":"B"}]}]}`

// start builds the binary, prepares fakes and the temp dirs, and runs `setu serve`.
func start(t *testing.T) *server {
	t.Helper()
	bin := buildBinary(t)
	root := t.TempDir()
	s := &server{t: t, fb: filepath.Join(root, "fb"), home: filepath.Join(root, "setu-home"), hm: filepath.Join(root, "home"), log: &bytes.Buffer{}}
	for _, d := range []string{s.home, s.hm} {
		os.MkdirAll(d, 0o755)
	}
	fakebin.Install(t, s.fb) // PATH and FAKEBIN_FIXTURES for this process; the child inherits them

	// blubird: a fake installed plugin under CLAUDE_CONFIG_DIR
	cfg := filepath.Join(s.hm, ".claude")
	inst := filepath.Join(cfg, "plugins", "cache", "agentic-workflow", "blubird", "1.2.3")
	write(t, filepath.Join(inst, "skills", "create-prd", "SKILL.md"), "---\nname: create-prd\n---\nbody\n")
	write(t, filepath.Join(cfg, "plugins", "installed_plugins.json"),
		fmt.Sprintf(`{"version":2,"plugins":{"blubird@agentic-workflow":[{"scope":"user","installPath":%q,"version":"1.2.3"}]}}`, inst))

	// a registered repo for the release flow
	repo := filepath.Join(root, "app")
	for _, a := range [][]string{{"init", "-q", repo}, {"-C", repo, "remote", "add", "origin", "https://github.com/acme/app.git"},
		{"-C", repo, "-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"}} {
		if out, err := exec.Command("git", a...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", a, err, out)
		}
	}
	write(t, filepath.Join(s.home, "checkouts.json"), fmt.Sprintf(`{%q:%q}`, "acme/app", repo))
	write(t, filepath.Join(s.home, ".migrated"), "")

	ask := write(t, filepath.Join(s.fb, "ask.jsonl"), jl(
		obj{"type": "system", "subtype": "init", "session_id": "sess-1", "model": "claude-opus-5-5"},
		obj{"type": "assistant", "message": obj{"content": []any{obj{"type": "text", "text": "I have a question"}}}},
		obj{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": 0.1, "result": "asked", "usage": obj{"input_tokens": 1, "output_tokens": 1}}))
	after := write(t, filepath.Join(s.fb, "after.jsonl"), jl(
		obj{"type": "system", "subtype": "init", "session_id": "sess-1", "model": "claude-opus-5-5"},
		obj{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": 0.2, "result": "thanks", "usage": obj{"input_tokens": 1, "output_tokens": 1}}))
	rel := write(t, filepath.Join(s.fb, "release.jsonl"), jl(
		obj{"type": "system", "subtype": "init", "session_id": "sess-rel", "model": "claude-opus-5-5"},
		obj{"type": "assistant", "message": obj{"content": []any{obj{"type": "text", "text": "cut done\nSETU-RELEASE: {\"pr\":\"https://github.com/acme/app/pull/77\",\"thread\":null}"}}}},
		obj{"type": "result", "subtype": "success", "is_error": false, "total_cost_usd": 0.3, "result": "cut done\nSETU-RELEASE: {\"pr\":\"https://github.com/acme/app/pull/77\",\"thread\":null}", "usage": obj{"input_tokens": 1, "output_tokens": 1}}))
	issues := write(t, filepath.Join(s.fb, "issues.json"), `{"data":{"repository":{"i0":{"number":1,"title":"First","state":"OPEN","repository":{"nameWithOwner":"acme/app"},"labels":{"nodes":[]},"blockedBy":{"nodes":[]}}}}}`)
	fakebin.WriteRules(t, s.fb, []fakebin.Rule{
		{Bin: "gh", ArgsPrefix: []string{"auth", "status"}, Stdout: "Logged in to github.com account tester"},
		{Bin: "gh", ArgsPrefix: []string{"api", "user"}, Stdout: `{"login":"tester"}`},
		{Bin: "gh", ArgsContains: "graphql", StdoutFile: issues},
		{Bin: "claude", ArgsContains: "--resume", StdoutFile: after},
		{Bin: "claude", ArgsContains: "SETU-RELEASE", Exec: []string{"cat", rel}},
		{Bin: "claude", ArgsContains: "ask me", Exec: []string{"sh", "-c", "cat " + ask + "; setu ask --json '" + askQ + "'"}},
		{Bin: "claude", ArgsContains: "--print", Exec: []string{"cat", rel}},
	})

	port := freePort(t)
	s.base = fmt.Sprintf("http://127.0.0.1:%d", port)
	ctx, cancel := context.WithCancel(context.Background())
	s.cmd = exec.CommandContext(ctx, bin, "serve", "--port", fmt.Sprint(port), "--no-tailscale")
	s.cmd.Env = append(os.Environ(), "SETU_HOME="+s.home, "HOME="+s.hm, "CLAUDE_CONFIG_DIR="+cfg,
		"SETU_NO_MAC_BANNER=1", "AIW_NO_MAC_BANNER=1", "SETU_MIGRATE_FROM="+filepath.Join(root, "no-old-dir"), "TERM=dumb")
	s.cmd.Stdout, s.cmd.Stderr = s.log, s.log
	s.cmd.Cancel = func() error { return s.cmd.Process.Signal(os.Interrupt) }
	s.cmd.WaitDelay = 5 * time.Second
	if err := s.cmd.Start(); err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	go func() { s.cmd.Wait(); close(done) }()
	t.Cleanup(func() {
		cancel()
		select {
		case <-done:
		case <-time.After(10 * time.Second):
			s.cmd.Process.Kill()
		}
		if t.Failed() {
			t.Logf("server log:\n%s", s.log.String())
		}
	})
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		if r, err := http.Get(s.base + "/api/health"); err == nil {
			r.Body.Close()
			go s.listen(ctx)
			return s
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("server did not start:\n%s", s.log.String())
	return nil
}

// listen collects the SSE stream.
func (s *server) listen(ctx context.Context) {
	req, _ := http.NewRequestWithContext(ctx, "GET", s.base+"/api/events", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return
	}
	defer resp.Body.Close()
	sc := bufio.NewScanner(resp.Body)
	ev := ""
	for sc.Scan() {
		l := sc.Text()
		switch {
		case strings.HasPrefix(l, "event: "):
			ev = strings.TrimPrefix(l, "event: ")
		case strings.HasPrefix(l, "data: "):
			s.mu.Lock()
			s.events = append(s.events, ev+" "+strings.TrimPrefix(l, "data: "))
			s.mu.Unlock()
		}
	}
}

func (s *server) sawEvent(prefix string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, e := range s.events {
		if strings.HasPrefix(e, prefix) {
			return true
		}
	}
	return false
}

func (s *server) do(method, path string, body any) (int, obj) {
	s.t.Helper()
	var rd io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rd = bytes.NewReader(b)
	}
	req, _ := http.NewRequest(method, s.base+path, rd)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		s.t.Fatal(err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	var out obj
	if err := json.Unmarshal(b, &out); err != nil {
		s.t.Fatalf("%s %s: not a JSON object (%d): %s", method, path, resp.StatusCode, b)
	}
	return resp.StatusCode, out
}

func (s *server) must(method, path string, body any, want int) obj {
	s.t.Helper()
	st, out := s.do(method, path, body)
	if st != want {
		s.t.Fatalf("%s %s = %d, want %d: %v", method, path, st, want, out)
	}
	return out
}

func (s *server) waitFor(what string, f func() bool) {
	s.t.Helper()
	deadline := time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		if f() {
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
	s.t.Fatalf("timed out waiting for %s", what)
}

func items(inbox obj) []obj {
	var out []obj
	for _, x := range inbox["items"].([]any) {
		out = append(out, x.(obj))
	}
	return out
}

func run(s *server, name string, f func(t *testing.T)) {
	parent := s.t
	parent.Run(name, func(t *testing.T) {
		s.t = t
		defer func() { s.t = parent }()
		f(t)
	})
}

func TestEndToEnd(t *testing.T) {
	s := start(t)

	run(s, "health and status", func(t *testing.T) {
		if out := s.must("GET", "/api/health", nil, 200); out["ok"] != true {
			t.Fatal(out)
		}
		st := s.must("GET", "/api/status", nil, 200)
		if st["version"] == nil || st["boot_id"] == "" {
			t.Fatalf("%v", st)
		}
	})

	run(s, "registry", func(t *testing.T) {
		reg := s.must("GET", "/api/registry", nil, 200)
		steps := reg["steps"].([]any)
		found := map[string]obj{}
		for _, x := range steps {
			st := x.(obj)
			found[st["id"].(string)] = st
		}
		for _, id := range []string{"release-pr", "pr-grind", "create-prd", "implement-issue"} {
			st, ok := found[id]
			if !ok {
				t.Fatalf("step %s missing", id)
			}
			for _, k := range []string{"source", "skill", "runs_in", "stage", "args_hint", "command", "available"} {
				if _, ok := st[k]; !ok {
					t.Fatalf("step %s lacks %q: %v", id, k, st)
				}
			}
			if st["available"] != true {
				t.Fatalf("step %s not available: %v", id, st)
			}
		}
	})

	run(s, "blubird status", func(t *testing.T) {
		b := s.must("GET", "/api/blubird", nil, 200)
		if b["installed"] != true || b["version"] != "1.2.3" {
			t.Fatalf("%v", b)
		}
		skills, _ := b["skills"].([]any)
		if len(skills) != 1 || skills[0] != "create-prd" {
			t.Fatalf("skills %v", b["skills"])
		}
	})

	run(s, "settings round trip", func(t *testing.T) {
		before := s.must("GET", "/api/settings", nil, 200)
		if before["grind_mode"] != "deep" {
			t.Fatalf("default grind_mode %v", before["grind_mode"])
		}
		after := s.must("PUT", "/api/settings", obj{"grind_mode": "simple"}, 200)
		if after["grind_mode"] != "simple" {
			t.Fatalf("%v", after["grind_mode"])
		}
		again := s.must("GET", "/api/settings", nil, 200)
		if again["grind_mode"] != "simple" {
			t.Fatalf("not persisted: %v", again["grind_mode"])
		}
		n := s.must("GET", "/api/settings/notify", nil, 200)
		for _, k := range []string{"matrix", "events", "ntfy_ready", "server", "topic", "token_set"} {
			if _, ok := n[k]; !ok {
				t.Fatalf("notify settings lack %q", k)
			}
		}
	})

	run(s, "question, answer, resume, inbox", func(t *testing.T) {
		sess := s.must("POST", "/api/sessions", obj{"text": "ask me something", "repo": "acme/app"}, 201)
		id := sess["id"].(string)
		s.waitFor("session waiting", func() bool {
			_, g := s.do("GET", "/api/sessions/"+id, nil)
			return g["waiting"] == true && g["pending_question"] != nil
		})
		_, g := s.do("GET", "/api/sessions/"+id, nil)
		rid := g["pending_question"].(obj)["id"].(string)

		var q obj
		for _, it := range items(s.must("GET", "/api/inbox", nil, 200)) {
			if it["session_id"] == id && it["type"] == "question" {
				q = it
			}
		}
		if q == nil {
			t.Fatalf("question not in the inbox")
		}
		s.must("POST", "/api/sessions/"+id+"/answer", obj{"round_id": rid, "answers": obj{"0": obj{"labels": []string{"B"}}}}, 200)
		s.waitFor("session done", func() bool {
			_, g := s.do("GET", "/api/sessions/"+id, nil)
			return g["status"] == "done"
		})
		for _, it := range items(s.must("GET", "/api/inbox", nil, 200)) {
			if it["session_id"] == id && it["type"] == "question" {
				t.Fatalf("answered question still in the inbox")
			}
		}
		list := s.must("GET", "/api/sessions", nil, 200)
		if len(list["sessions"].([]any)) == 0 {
			t.Fatal("no sessions listed")
		}
	})

	run(s, "release cut parses SETU-RELEASE", func(t *testing.T) {
		r := s.must("POST", "/api/releases", obj{"repo": "acme/app"}, 201)
		id := r["id"].(string)
		var last obj
		defer func() {
			if t.Failed() {
				t.Logf("last release: %v", last)
				if cs, ok := last["cut_session"].(string); ok {
					_, g := s.do("GET", "/api/sessions/"+cs, nil)
					t.Logf("cut session: status=%v error=%v", g["status"], g["error"])
					_, st := s.do("GET", "/api/sessions/"+cs+"/stream", nil)
					t.Logf("stream: %v", st)
				}
			}
		}()
		s.waitFor("release in grind stage with its PR", func() bool {
			_, last = s.do("GET", "/api/releases/"+id, nil)
			return last["stage"] == "grind" && last["pr"] == float64(77)
		})
		_, g := s.do("GET", "/api/releases/"+id, nil)
		if g["pr_url"] != "https://github.com/acme/app/pull/77" {
			t.Fatalf("%v", g)
		}
	})

	run(s, "dispatch preview", func(t *testing.T) {
		p := s.must("POST", "/api/dispatches/plan", obj{"issues": []string{"acme/app#1"}}, 200)
		b, _ := json.Marshal(p)
		if !strings.Contains(string(b), "acme/app") {
			t.Fatalf("plan: %s", b)
		}
	})

	run(s, "sse events", func(t *testing.T) {
		s.waitFor("hello", func() bool { return s.sawEvent("hello") })
		s.waitFor("a sessions event", func() bool { return s.sawEvent("sessions") })
	})

	run(s, "cli verbs", func(t *testing.T) {
		out, err := exec.Command("go", "run", "../cmd/setu", "version").CombinedOutput()
		if err != nil || !strings.HasPrefix(string(out), "setu ") {
			t.Fatalf("%v %s", err, out)
		}
	})
}
