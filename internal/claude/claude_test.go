package claude

import (
	"bufio"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/settings"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

func env(t *testing.T) (dir string, st *settings.Store, bus *events.Bus) {
	t.Helper()
	root := t.TempDir()
	t.Setenv("HOME", root)
	t.Setenv("CLAUDE_CONFIG_DIR", "")
	t.Setenv("SETU_HOME", filepath.Join(root, ".setu"))
	dir = filepath.Join(root, "fake")
	fakebin.Install(t, dir)
	h, err := home.Open()
	if err != nil {
		t.Fatal(err)
	}
	bus = events.New()
	return dir, settings.Open(h, bus), bus
}

func rules(t *testing.T, dir string, r ...fakebin.Rule) { t.Helper(); fakebin.WriteRules(t, dir, r) }

func lines(t *testing.T, name string) [][]byte {
	t.Helper()
	f, err := os.Open(filepath.Join("testdata", name))
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	var out [][]byte
	sc := bufio.NewScanner(f)
	sc.Buffer(nil, 1<<20)
	for sc.Scan() {
		out = append(out, append([]byte(nil), sc.Bytes()...))
	}
	return out
}

func kinds(evs []Event) string {
	var k []string
	for _, e := range evs {
		k = append(k, e.Kind)
	}
	return strings.Join(k, ",")
}

func TestParseLineTable(t *testing.T) {
	tests := []struct {
		name, line string
		kinds      string
		check      func(t *testing.T, e []Event)
	}{
		{"invalid json", `not json`, "", nil},
		{"non object", `[1]`, "", nil},
		{"user line ignored", `{"type":"user","message":{}}`, "", nil},
		{"text+tool", `{"type":"assistant","message":{"content":[{"type":"text","text":"hi"},{"type":"tool_use","name":"Bash","input":{"command":"ls"}},{"type":"text","text":5},{"type":"tool_use","name":7},"x"]}}`, "text,tool", func(t *testing.T, e []Event) {
			if e[0].Text != "hi" || e[1].Name != "Bash" || string(e[1].Input) != `{"command":"ls"}` {
				t.Fatalf("%+v", e)
			}
		}},
		{"assistant bad content", `{"type":"assistant","message":{"content":"x"}}`, "", nil},
		{"init", `{"type":"system","subtype":"init","session_id":"s1","model":"opus"}`, "session_id", func(t *testing.T, e []Event) {
			if e[0].SessionID != "s1" || e[0].Model != "opus" {
				t.Fatalf("%+v", e)
			}
		}},
		{"init empty model", `{"type":"system","subtype":"init","session_id":"s1","model":""}`, "session_id", func(t *testing.T, e []Event) {
			if e[0].Model != "" {
				t.Fatal()
			}
		}},
		{"result ok", `{"type":"result","total_cost_usd":0.5,"is_error":false,"result":"done","usage":{"input_tokens":3,"cache_creation_input_tokens":2,"cache_read_input_tokens":5,"output_tokens":7}}`, "result", func(t *testing.T, e []Event) {
			r := e[0]
			if *r.Cost != 0.5 || r.IsError || r.Text != "done" || *r.Tokens != (Tokens{10, 5, 7}) || r.Error != "" {
				t.Fatalf("%+v %+v", r, r.Tokens)
			}
		}},
		{"result cost bool", `{"type":"result","total_cost_usd":true}`, "result", func(t *testing.T, e []Event) {
			if e[0].Cost != nil || e[0].Tokens != nil {
				t.Fatalf("%+v", e[0])
			}
		}},
		{"result error list", `{"type":"result","is_error":true,"result":"x","errors":["boom",2]}`, "result", func(t *testing.T, e []Event) {
			if !e[0].IsError || e[0].Error != "boom" {
				t.Fatalf("%+v", e[0])
			}
		}},
		{"errors ignored when not is_error", `{"type":"result","is_error":false,"errors":["boom"]}`, "result", func(t *testing.T, e []Event) {
			if e[0].Error != "" {
				t.Fatal()
			}
		}},
		{"limit", `{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resetsAt":1700000000,"rateLimitType":"five_hour"}}`, "limit", func(t *testing.T, e []Event) {
			if *e[0].ResetsAt != 1700000000 || e[0].LimitType != "five_hour" || !strings.Contains(string(e[0].Info), `"rejected"`) {
				t.Fatalf("%+v", e[0])
			}
		}},
		{"limit float resets", `{"type":"rate_limit_event","rate_limit_info":{"resetsAt":1700000000.9}}`, "limit", func(t *testing.T, e []Event) {
			if *e[0].ResetsAt != 1700000000 {
				t.Fatal(*e[0].ResetsAt)
			}
		}},
		{"limit no resets", `{"type":"rate_limit_event","rate_limit_info":{"resetsAt":"soon"}}`, "limit", func(t *testing.T, e []Event) {
			if e[0].ResetsAt != nil {
				t.Fatal()
			}
		}},
		{"limit not object", `{"type":"rate_limit_event","rate_limit_info":3}`, "", nil},
		{"guard before result, notebook edit", `{"type":"result","permission_denials":[{"tool_name":"NotebookEdit","tool_input":{"notebook_path":"/r/AGENTS.md"}},{"tool_name":"Edit","tool_input":{"file_path":"/r/src/a.go"}},{"tool_name":"Bash","tool_input":{"file_path":"/r/CLAUDE.md"}}]}`, "guard_ask,result", func(t *testing.T, e []Event) {
			if len(e[0].Edits) != 1 {
				t.Fatalf("%+v", e[0].Edits)
			}
		}},
		{"hook response", `{"type":"system","subtype":"hook_response","hook_name":"h","hook_event":"PreToolUse","output":"","stdout":"out"}`, "hook", func(t *testing.T, e []Event) {
			if e[0].Name != "h" || e[0].HookEvent != "PreToolUse" || e[0].Text != "out" {
				t.Fatalf("%+v", e[0])
			}
		}},
		{"hook text cut", `{"type":"system","subtype":"hook_x","output":"` + strings.Repeat("é", 600) + `"}`, "hook", func(t *testing.T, e []Event) {
			if len([]rune(e[0].Text)) != 500 {
				t.Fatal(len(e[0].Text))
			}
		}},
		{"hook started skipped", `{"type":"system","subtype":"hook_started","hook_name":"h"}`, "", nil},
		{"other system", `{"type":"system","subtype":"compact"}`, "", nil},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			e := ParseLine([]byte(tc.line))
			if kinds(e) != tc.kinds {
				t.Fatalf("kinds %q want %q", kinds(e), tc.kinds)
			}
			if tc.check != nil {
				tc.check(t, e)
			}
		})
	}
}

func TestTokensOf(t *testing.T) {
	for _, tc := range []struct {
		in   string
		want *Tokens
	}{
		{`null`, nil}, {`"x"`, nil}, {`{}`, nil}, {`{"input_tokens":0,"output_tokens":0}`, nil},
		{`{"input_tokens":1.5,"output_tokens":2}`, &Tokens{0, 0, 2}},
		{`{"input_tokens":-4,"output_tokens":true,"cache_read_input_tokens":"9"}`, nil},
		{`{"input_tokens":4,"output_tokens":0}`, &Tokens{4, 0, 0}},
		{`{"cache_read_input_tokens":6}`, &Tokens{6, 6, 0}},
	} {
		got := TokensOf(json.RawMessage(tc.in))
		if (got == nil) != (tc.want == nil) || (got != nil && *got != *tc.want) {
			t.Errorf("%s: %+v want %+v", tc.in, got, tc.want)
		}
	}
}

func TestFixtures(t *testing.T) {
	g := lines(t, "claude_guard_ask.jsonl")
	var all []Event
	for _, l := range g {
		all = append(all, ParseLine(l)...)
	}
	if kinds(all) != "session_id,tool,text,guard_ask,result" {
		t.Fatal(kinds(all))
	}
	if all[0].SessionID != "sess-guard" || *all[4].Cost != 0.04 || *all[4].Tokens != (Tokens{20, 0, 30}) {
		t.Fatalf("%+v", all)
	}
	var d struct {
		ToolName string `json:"tool_name"`
	}
	_ = json.Unmarshal(all[3].Edits[0], &d)
	if d.ToolName != "Edit" {
		t.Fatal(d)
	}

	all = nil
	for _, l := range lines(t, "claude_secret_block.jsonl") {
		all = append(all, ParseLine(l)...)
	}
	if kinds(all) != "session_id,prompt_blocked,result" {
		t.Fatal(kinds(all))
	}
	if !strings.HasPrefix(all[1].Reason, "This prompt was not sent because it contains a secret") || strings.Contains(all[1].Reason, "Original prompt") {
		t.Fatalf("%q", all[1].Reason)
	}
	if e := ParseLine([]byte(`{"type":"result","result":"UserPromptSubmit operation blocked by hook:   \n\nOriginal prompt: x"}`)); e[0].Reason != "the prompt holds a secret" {
		t.Fatalf("%+v", e[0])
	}

	all = nil
	for _, l := range lines(t, "claude_hooks.jsonl") {
		all = append(all, ParseLine(l)...)
	}
	if kinds(all) != "hook,session_id,hook,result" || all[0].Name != "SessionStart:startup" || all[0].Text != "blubird ready\n" {
		t.Fatalf("%s %+v", kinds(all), all[0])
	}
}

func TestArgvAndConfigDir(t *testing.T) {
	dir, _, _ := env(t)
	for _, n := range []string{"cc-profile", "cc"} {
		if err := os.WriteFile(filepath.Join(dir, n), []byte("#!/bin/sh\n"), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	a, err := Argv("cc masum")
	if err != nil || a[0] != filepath.Join(dir, "cc-profile") || a[1] != "masum" {
		t.Fatalf("%v %v", a, err)
	}
	if _, err := Argv("not-a-real-binary-xyz"); err == nil || !strings.Contains(err.Error(), "not found on PATH") {
		t.Fatal(err)
	}
	home, _ := os.UserHomeDir()
	for cmd, want := range map[string]string{
		"claude":         filepath.Join(home, ".claude"),
		"cc masum":       filepath.Join(home, ".claude-profiles", "masum"),
		"cc-profile x y": filepath.Join(home, ".claude-profiles", "x"),
		"cc":             filepath.Join(home, ".claude"),
	} {
		if got := ConfigDir(cmd); got != want {
			t.Errorf("%q: %s want %s", cmd, got, want)
		}
	}
	t.Setenv("CLAUDE_CONFIG_DIR", "/alt")
	if ConfigDir("claude") != "/alt" || ConfigDir("cc p") != filepath.Join(home, ".claude-profiles", "p") {
		t.Fatal("CLAUDE_CONFIG_DIR")
	}
}

func TestPreflight(t *testing.T) {
	dir, _, _ := env(t)
	ctx := context.Background()
	check := func(isDefault bool, cmd, want string) {
		t.Helper()
		err := Preflight(ctx, cmd, isDefault)
		if want == "" {
			if err != nil {
				t.Fatalf("%s: %v", cmd, err)
			}
			return
		}
		if err == nil || errs.KindOf(err) != errs.KUpstream || err.Error() != want {
			t.Fatalf("%s: got %v want %q", cmd, err, want)
		}
	}
	check(true, "claude", "") // fakebin default: logged in

	rules(t, dir, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"auth", "status"}, Stdout: `{"loggedIn":false}`})
	check(true, "claude", "claude CLI is not logged in, run `claude auth login`")
	rules(t, dir, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"auth", "status"}, Stdout: `[]`})
	check(false, "claude", "claude CLI is not logged in, run `claude auth login`")
	rules(t, dir, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"auth", "status"}, Stdout: `{"loggedIn":"yes"}`})
	check(true, "claude", "claude CLI is not logged in, run `claude auth login`")
	rules(t, dir, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"auth", "status"}, Stdout: `garbage`})
	err := Preflight(ctx, "claude", true)
	if err == nil || !strings.HasPrefix(err.Error(), "claude CLI is not logged in, run `claude auth login` (auth status check failed: ") {
		t.Fatal(err)
	}
	rules(t, dir, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"auth", "status"}, Stdout: `{"loggedIn":true}`})
	check(true, "claude", "")

	// non-default account: its own command in the message
	if err := os.WriteFile(filepath.Join(dir, "cc-profile"), []byte("#!/bin/sh\necho '{\"loggedIn\":false}'\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	check(false, "cc work", "claude CLI is not logged in, run `cc work auth login`")
	check(false, "zz-missing --x", "claude command 'zz-missing --x' unusable: 'zz-missing' not found on PATH")
	t.Setenv("PATH", t.TempDir())
	check(true, "claude", "claude CLI not found on PATH")
}

func TestPreflightTimeout(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "slowclaude"), []byte("#!/bin/sh\nsleep 5\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+":"+os.Getenv("PATH"))
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	err := Preflight(ctx, "slowclaude", false)
	if err == nil || !strings.Contains(err.Error(), "run `slowclaude auth login` (auth status check failed:") {
		t.Fatal(err)
	}
}

func TestTestAccount(t *testing.T) {
	dir, _, _ := env(t)
	ctx := context.Background()
	rules(t, dir, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"auth", "status"}, Stdout: `{"loggedIn":true,"email":"a@b.c"}`})
	if ok, msg := TestAccount(ctx, "claude"); !ok || msg != "logged in a@b.c" {
		t.Fatal(ok, msg)
	}
	rules(t, dir, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"auth", "status"}, Stdout: `{"loggedIn":true}`})
	if ok, msg := TestAccount(ctx, "claude"); !ok || msg != "logged in" {
		t.Fatal(ok, msg)
	}
	rules(t, dir, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"auth", "status"}, Stdout: `{"loggedIn":false}`})
	if ok, msg := TestAccount(ctx, "claude"); ok || msg != "not logged in" {
		t.Fatal(ok, msg)
	}
	rules(t, dir, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"auth", "status"}, Stdout: `nope`})
	if ok, msg := TestAccount(ctx, "claude"); ok || !strings.HasPrefix(msg, "auth status check failed: ") {
		t.Fatal(ok, msg)
	}
	if ok, msg := TestAccount(ctx, "zz-nothing"); ok || !strings.Contains(msg, "not found on PATH") {
		t.Fatal(ok, msg)
	}
}

func TestCopyTranscript(t *testing.T) {
	env(t)
	home, _ := os.UserHomeDir()
	cwd := filepath.Join(t.TempDir(), "my.proj")
	if err := os.MkdirAll(cwd, 0o755); err != nil {
		t.Fatal(err)
	}
	real, _ := filepath.EvalSymlinks(cwd)
	slug := nonAlnum.ReplaceAllString(real, "-")
	if ProjectDirName(cwd) != slug {
		t.Fatal(ProjectDirName(cwd), slug)
	}
	err := CopyTranscript("claude", "cc other", cwd, "sess-1")
	if errs.KindOf(err) != errs.KConflict || !strings.Contains(err.Error(), "transcript not found at "+filepath.Join(home, ".claude", "projects", slug, "sess-1.jsonl")) {
		t.Fatal(err)
	}
	src := filepath.Join(home, ".claude", "projects", slug)
	if err := os.MkdirAll(src, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(src, "sess-1.jsonl"), []byte("{\"a\":1}\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := CopyTranscript("claude", "cc other", cwd, "sess-1"); err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(filepath.Join(home, ".claude-profiles", "other", "projects", slug, "sess-1.jsonl"))
	if err != nil || string(b) != "{\"a\":1}\n" {
		t.Fatalf("%v %q", err, b)
	}
	if CopyTranscript("claude", "claude", cwd, "sess-1") != nil {
		t.Fatal("same dir is a no-op")
	}
	if errs.KindOf(CopyTranscript("claude", "cc other", cwd, "../x")) != errs.KInvalid {
		t.Fatal("traversal")
	}
}

func fakeKeychain(token string, expiresMs int64) func(context.Context, string) ([]byte, error) {
	return func(ctx context.Context, service string) ([]byte, error) {
		b, _ := json.Marshal(map[string]any{"claudeAiOauth": map[string]any{"accessToken": token, "expiresAt": expiresMs}})
		return b, nil
	}
}

func TestKeychainService(t *testing.T) {
	env(t)
	home, _ := os.UserHomeDir()
	if KeychainService("claude") != "Claude Code-credentials" {
		t.Fatal(KeychainService("claude"))
	}
	got := KeychainService("cc masum")
	want := "Claude Code-credentials-" + shaHex8(filepath.Join(home, ".claude-profiles", "masum"))
	if got != want || len(got) != len("Claude Code-credentials-")+8 {
		t.Fatalf("%s want %s", got, want)
	}
}

func TestKeychainViaFakebin(t *testing.T) {
	dir, _, _ := env(t)
	rules(t, dir, fakebin.Rule{Bin: "security", ArgsPrefix: []string{"find-generic-password", "-s", "Claude Code-credentials", "-w"}, Stdout: `{"claudeAiOauth":{"accessToken":"t","expiresAt":1}}`})
	out, err := readKeychain(context.Background(), "Claude Code-credentials")
	if err != nil || !strings.Contains(string(out), "accessToken") {
		t.Fatal(err)
	}
	if _, err := readKeychain(context.Background(), "other"); err == nil { // fakebin: no rule -> exit 99
		t.Fatal("denied keychain must error")
	}
}

func usageSetup(t *testing.T, handler http.HandlerFunc) (*Usage, *events.Bus) {
	t.Helper()
	_, st, bus := env(t)
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)
	now := time.Unix(1_800_000_000, 0)
	u := NewUsage(st, bus, func() bool { return true })
	u.url, u.client, u.now = srv.URL, srv.Client(), func() time.Time { return now }
	u.keychain = fakeKeychain("tok-secret", (now.Unix()+3600)*1000)
	return u, bus
}

func TestUsageFetch(t *testing.T) {
	var hits atomic.Int32
	var gotAuth, gotBeta string
	u, bus := usageSetup(t, func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		gotAuth, gotBeta = r.Header.Get("Authorization"), r.Header.Get("anthropic-beta")
		w.Write([]byte(`{"five_hour":{"utilization":12.5,"resets_at":"2026-11-12T10:00:00Z"},"seven_day":{"utilization":"x"}}`))
	})
	ch, cancel := bus.Subscribe(8)
	defer cancel()
	u.Refresh(context.Background())
	if hits.Load() != 1 || gotAuth != "Bearer tok-secret" || gotBeta != "oauth-2025-04-20" {
		t.Fatal(hits.Load(), gotAuth, gotBeta)
	}
	snap := u.Snapshot()["claude"]
	if snap.Label != "claude" || snap.FiveHour == nil || snap.FiveHour.Pct != 12.5 || *snap.FiveHour.ResetsAt != "2026-11-12T10:00:00Z" || snap.SevenDay != nil || snap.Error != nil || *snap.At != 1_800_000_000 {
		t.Fatalf("%+v", snap)
	}
	if e := <-ch; e.Topic != events.TUsage {
		t.Fatalf("%+v", e)
	}
	u.Refresh(context.Background()) // within POLL: no second fetch
	if hits.Load() != 1 {
		t.Fatal("refetched inside the poll window")
	}
	// after POLL it fetches again
	base := u.now()
	u.now = func() time.Time { return base.Add(usagePoll + time.Second) }
	u.keychain = fakeKeychain("tok-secret", (base.Unix()+10_000)*1000)
	u.Refresh(context.Background())
	if hits.Load() != 2 {
		t.Fatal("no refetch after poll")
	}
}

func TestUsageErrors(t *testing.T) {
	good := true
	u, _ := usageSetup(t, func(w http.ResponseWriter, r *http.Request) {
		if good {
			w.Write([]byte(`{"five_hour":{"utilization":50,"resets_at":null}}`))
			return
		}
		http.Error(w, "nope", 500)
	})
	ctx := context.Background()
	u.Refresh(ctx)
	// server error keeps the last numbers, sets error, retries after RETRY
	good = false
	base := u.now()
	u.now = func() time.Time { return base.Add(usagePoll + time.Second) }
	u.keychain = fakeKeychain("t", (base.Unix()+99_999)*1000)
	u.Refresh(ctx)
	s := u.Snapshot()["claude"]
	if s.Error == nil || *s.Error != "usage unavailable" || s.FiveHour == nil || s.FiveHour.Pct != 50 || *s.At != base.Unix() {
		t.Fatalf("%+v", s)
	}
	if e := u.cache["claude"]; !e.next.Equal(u.now().Add(usageRetry)) {
		t.Fatal(e.next)
	}
	// expired token
	u.now = func() time.Time { return base.Add(usagePoll + usageRetry + 10*time.Second) }
	u.keychain = fakeKeychain("t", 1000)
	u.Refresh(ctx)
	if s := u.Snapshot()["claude"]; s.Error == nil || *s.Error != "re-login needed" {
		t.Fatalf("%+v", s)
	}
	// keychain denied
	u.now = func() time.Time { return base.Add(10 * time.Hour) }
	u.keychain = func(context.Context, string) ([]byte, error) { return nil, os.ErrPermission }
	u.Refresh(ctx)
	if s := u.Snapshot()["claude"]; *s.Error != "usage unavailable (keychain read denied or no login)" {
		t.Fatalf("%+v", s)
	}
	// malformed credentials
	u.now = func() time.Time { return base.Add(20 * time.Hour) }
	u.keychain = func(context.Context, string) ([]byte, error) { return []byte(`{"x":1}`), nil }
	u.Refresh(ctx)
	if s := u.Snapshot()["claude"]; *s.Error != "usage unavailable" {
		t.Fatalf("%+v", s)
	}
}

func TestUsageOnlyWhilePresent(t *testing.T) {
	var hits atomic.Int32
	u, _ := usageSetup(t, func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.Write([]byte(`{}`))
	})
	var present atomic.Bool
	u.present = present.Load
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	// drive the tick body directly, as Start's loop does
	tick := func() {
		if u.present() {
			u.tick(ctx)
		}
	}
	tick()
	if hits.Load() != 0 {
		t.Fatal("fetched with no UI present")
	}
	present.Store(true)
	tick()
	if hits.Load() != 1 {
		t.Fatal("no fetch while present")
	}
	u.Start(ctx) // returns at once
}

func TestTestAccountRoute(t *testing.T) {
	dir, st, _ := env(t)
	rules(t, dir, fakebin.Rule{Bin: "claude", ArgsPrefix: []string{"auth", "status"}, Stdout: `{"loggedIn":true,"email":"me@x.y"}`})
	mux := http.NewServeMux()
	for _, r := range Routes(Deps{Settings: st}) {
		mux.Handle(r.Pattern, r.Handler)
	}
	post := func(body string) (int, string) {
		req := httptest.NewRequest("POST", "/api/settings/test-account", strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		return rec.Code, strings.TrimSpace(rec.Body.String())
	}
	if c, b := post(`{"label":"claude"}`); c != 200 || b != `{"message":"logged in me@x.y","ok":true}` {
		t.Fatal(c, b)
	}
	if c, b := post(`{"label":""}`); c != 200 || !strings.Contains(b, `"ok":false`) {
		t.Fatal(c, b)
	}
	if c, b := post(`{"label":"ghost"}`); c != 400 || !strings.Contains(b, "save the account first") {
		t.Fatal(c, b)
	}
}

func TestIdleHookParseBlock(t *testing.T) {
	block := ParseLine([]byte(`{"type":"system","subtype":"hook_response","hook_name":"Stop","hook_event":"Stop","stdout":"{\"decision\":\"block\",\"reason\":\"Do not stop idle.\"}\n","exit_code":0}`))
	if len(block) != 1 || !block[0].Blocked || block[0].Text != "Do not stop idle." || block[0].HookEvent != "Stop" {
		t.Fatalf("%+v", block)
	}
	for _, out := range []string{`checked`, `{\"decision\":\"approve\"}`, `{not json`} {
		e := ParseLine([]byte(`{"type":"system","subtype":"hook_response","hook_name":"Stop","hook_event":"Stop","stdout":"` + out + `","exit_code":0}`))
		if len(e) != 1 || e[0].Blocked || e[0].Text == "" {
			t.Fatalf("%s: %+v", out, e)
		}
	}
}

// Recorded shape of claude -p 2.x: a blocking Stop hook shows as a "Stop hook feedback" user
// turn, never as a hook_response line.
func TestIdleHookParseStopFeedback(t *testing.T) {
	var all []Event
	for _, l := range lines(t, "claude_stop_block.jsonl") {
		all = append(all, ParseLine(l)...)
	}
	if kinds(all) != "session_id,text,hook,result" {
		t.Fatal(kinds(all))
	}
	if h := all[2]; !h.Blocked || h.HookEvent != "Stop" || h.Text != "Do not stop idle. test" {
		t.Fatalf("%+v", h)
	}
}
