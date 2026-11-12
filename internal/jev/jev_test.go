package jev

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

func setup(t *testing.T, rules []fakebin.Rule) (*Client, string, *home.Home) {
	t.Helper()
	bin := t.TempDir()
	fakebin.Install(t, bin)
	fakebin.WriteRules(t, bin, rules)
	t.Setenv("HOME", t.TempDir())
	t.Setenv("SETU_HOME", t.TempDir())
	h := &home.Home{Root: os.Getenv("SETU_HOME")}
	c := New(h, func() bool { return true })
	c.logf = func(string, ...any) {}
	return c, bin, h
}

func TestRedact(t *testing.T) {
	long := strings.Repeat("a", 40)
	tests := []struct{ name, in, want string }{
		{"ghp", "x ghp_" + strings.Repeat("A", 20) + " y", "x [redacted] y"},
		{"short prefix kept", "ghp_short", "ghp_short"},
		{"github_pat", "github_pat_" + strings.Repeat("a1_", 10), "[redacted]"},
		{"sk", "key sk-" + strings.Repeat("z", 20), "key [redacted]"},
		{"xox", "xoxb-" + strings.Repeat("1", 16), "[redacted]"},
		{"aws", "AKIA" + strings.Repeat("A", 16), "[redacted]"},
		{"hex32", strings.Repeat("ab", 16), "[redacted]"},
		{"hex31", strings.Repeat("a", 31), strings.Repeat("a", 31)},
		{"b64 40", long, "[redacted]"},
		{"b64 padding", strings.Repeat("z", 40) + "==", "[redacted]"},
		{"authorization line", "Authorization: Basic abc\nnext", "Authorization: [redacted]\nnext"},
		{"bearer", "got Bearer abc.def here", "got Bearer [redacted] here"},
		{"api_key assign", "API_KEY=hunter2 ok", "API_KEY=[redacted] ok"}, // gitleaks:allow
		{"token colon", "my.token: abc", "my.token: [redacted]"},
		{"secret", "client_secret = s3", "client_secret = [redacted]"},
		{"plain", "assertion failed at line 3", "assertion failed at line 3"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := Redact(tc.in); got != tc.want {
				t.Fatalf("Redact(%q) = %q, want %q", tc.in, got, tc.want)
			}
		})
	}
}

func TestStatus(t *testing.T) {
	c, _, _ := setup(t, nil)
	if c.Status() != "ok" {
		t.Fatal("want ok")
	}
	on := false
	c.enabled = func() bool { return on }
	if c.Status() != "off" {
		t.Fatal("want off")
	}
	on = true
	t.Setenv("PATH", t.TempDir())
	if c.Status() != "missing" {
		t.Fatal("want missing")
	}
}

func TestOffNeverExecs(t *testing.T) {
	c, bin, _ := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: `{"choice":"a"}`}})
	c.enabled = func() bool { return false }
	if a := c.Ask(context.Background(), "hints", "choice", "q", "t", nil, nil); a.Status != "off" {
		t.Fatalf("got %+v", a)
	}
	if c.Peek("urgency", "choice", "q", "t", nil, nil) != nil {
		t.Fatal("peek must be nil")
	}
	if n := len(fakebin.Calls(t, bin)); n != 0 {
		t.Fatalf("jev ran %d times", n)
	}
}

func TestAskParsing(t *testing.T) {
	tests := []struct {
		name, kind, out string
		exit            int
		want            Answer
	}{
		{"noul", "noul", `{"noul":0.25}`, 0, Answer{Status: "ok", P: 0.25}},
		{"choice prob", "choice", `{"choice":"fix","probabilities":{"fix":0.8,"rebut":0.2}}`, 0, Answer{Status: "ok", Choice: "fix", P: 0.8}},
		{"choice confidence", "choice", `{"choice":"fix","confidence":0.6}`, 0, Answer{Status: "ok", Choice: "fix", P: 0.6}},
		{"choice none", "choice", `{"choice":"fix"}`, 0, Answer{Status: "ok", Choice: "fix"}},
		{"score", "score", `{"score":3,"confidence":0.5}`, 0, Answer{Status: "ok", Score: 3, Confidence: 0.5}},
		{"bad json", "score", `nope`, 0, Answer{Status: "unreadable"}},
		{"missing field", "noul", `{}`, 0, Answer{Status: "unreadable"}},
		{"nonzero", "score", ``, 3, Answer{Status: "failed", Exit: 3}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			c, _, _ := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: tc.out, Exit: tc.exit}})
			if got := c.Ask(context.Background(), "hints", tc.kind, "q", "t", nil, nil); got != tc.want {
				t.Fatalf("got %+v want %+v", got, tc.want)
			}
		})
	}
}

func TestAskArgvAndStdin(t *testing.T) {
	c, bin, _ := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: `{"choice":"real"}`}})
	text := "log ghp_" + strings.Repeat("Q", 24) + " " + strings.Repeat("x ", 3000)
	c.Ask(context.Background(), "ci-hint", "choice", "Q?", text, map[string]string{"b": "2", "a": "1"}, []string{"L1"})
	calls := fakebin.Calls(t, bin)
	if len(calls) != 1 {
		t.Fatalf("calls %d", len(calls))
	}
	want := []string{"choice", "Q?", "--model", "jev-1.14.0", "--state-file", "-", "-o", "json", "--option", "a=1", "--option", "b=2", "--level", "L1"}
	if strings.Join(calls[0].Args, "\x00") != strings.Join(want, "\x00") {
		t.Fatalf("argv %q", calls[0].Args)
	}
	if strings.Contains(calls[0].Stdin, "ghp_") || len([]rune(calls[0].Stdin)) > MaxChars {
		t.Fatalf("stdin not redacted/cut (len %d)", len(calls[0].Stdin))
	}
}

func TestTimeoutIsNoAnswer(t *testing.T) {
	c, _, _ := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: `{"choice":"a"}`, SleepMs: 1500}})
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	if a := c.Ask(ctx, "hints", "choice", "q", "t", nil, nil); a.Status != "no_answer" {
		t.Fatalf("got %+v", a)
	}
}

func TestCacheAndCeiling(t *testing.T) {
	c, bin, h := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: `{"score":2,"confidence":0.9}`}})
	now := time.Unix(1_700_000_000, 0)
	c.now = func() time.Time { return now }
	ctx := context.Background()

	// not in server mode: urgency is counted but not cached
	c.Ask(ctx, "urgency", "score", "q", "t", nil, nil)
	c.Ask(ctx, "urgency", "score", "q", "t", nil, nil)
	if n := len(fakebin.Calls(t, bin)); n != 2 {
		t.Fatalf("no cache outside the server: %d calls", n)
	}
	if c.Spent() != 2 {
		t.Fatalf("spent %d", c.Spent())
	}
	c.Start(ctx)
	a := c.Ask(ctx, "urgency", "score", "q", "t", nil, nil)
	b := c.Ask(ctx, "urgency", "score", "q", "t", nil, nil)
	if a != b || len(fakebin.Calls(t, bin)) != 3 {
		t.Fatalf("second call should hit the cache: %d calls", len(fakebin.Calls(t, bin)))
	}
	if p := c.Peek("urgency", "score", "q", "t", nil, nil); p == nil || p.Score != 2 {
		t.Fatalf("peek %+v", p)
	}
	if c.Peek("urgency", "score", "q", "other", nil, nil) != nil {
		t.Fatal("peek miss must be nil")
	}
	// flush writes; a new client reads it back
	c.Flush()
	var onDisk map[string]entry
	if err := home.ReadJSON(filepath.Join(h.Root, "jev_cache.json"), &onDisk); err != nil || len(onDisk) != 1 {
		t.Fatalf("cache file: %v %v", err, onDisk)
	}
	c2 := New(h, func() bool { return true })
	c2.now = c.now
	if c2.Peek("urgency", "score", "q", "t", nil, nil) == nil {
		t.Fatal("cache not read from disk")
	}
	// expiry
	now = now.Add(MaxAge + time.Second)
	if c.Peek("urgency", "score", "q", "t", nil, nil) != nil {
		t.Fatal("entry should be stale after 7 days")
	}
	// ceiling: window restarted by the clock jump, then fill it
	c.mu.Lock()
	c.windowStart, c.windowCalls = now, Ceiling
	c.mu.Unlock()
	before := len(fakebin.Calls(t, bin))
	if a := c.Ask(ctx, "readiness", "score", "q2", "t", nil, nil); a.Status != "capped" {
		t.Fatalf("want capped, got %+v", a)
	}
	// uncached points are never refused or counted
	if a := c.Ask(ctx, "risk", "score", "q2", "t", nil, nil); a.Status != "ok" {
		t.Fatalf("risk %+v", a)
	}
	if len(fakebin.Calls(t, bin)) != before+1 || c.Spent() != Ceiling {
		t.Fatal("risk must run and not count")
	}
	// the window restarts after an hour
	now = now.Add(Window)
	if a := c.Ask(ctx, "readiness", "score", "q2", "t", nil, nil); a.Status != "ok" {
		t.Fatalf("after window: %+v", a)
	}
	// flush drops expired entries
	now = now.Add(MaxAge + time.Hour)
	c.mu.Lock()
	c.dirty = true
	c.mu.Unlock()
	c.Flush()
	onDisk = nil
	_ = home.ReadJSON(filepath.Join(h.Root, "jev_cache.json"), &onDisk)
	if len(onDisk) != 0 {
		t.Fatalf("expired entries kept: %d", len(onDisk))
	}
}

func TestFailedCallCountsAndIsNotCached(t *testing.T) {
	c, _, _ := setup(t, []fakebin.Rule{{Bin: "jev", Exit: 1}})
	c.Start(context.Background())
	if a := c.Ask(context.Background(), "duplicate", "score", "q", "t", nil, nil); a.Status != "failed" || a.Exit != 1 {
		t.Fatalf("%+v", a)
	}
	if c.Spent() != 1 || len(c.cache) != 0 {
		t.Fatalf("spent %d cache %d", c.Spent(), len(c.cache))
	}
}

func TestCacheEvictsOldestAt2000(t *testing.T) {
	c, _, _ := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: `{"score":1}`}})
	now := time.Unix(1_700_000_000, 0)
	c.now = func() time.Time { return now }
	c.Start(context.Background())
	c.mu.Lock()
	cache := c.load()
	for i := 0; i < MaxEntries; i++ {
		cache["k"+string(rune('a'+i%26))+strings.Repeat("x", i/26)] = entry{At: float64(now.Unix()) - 100 - float64(i)}
	}
	c.mu.Unlock()
	c.Ask(context.Background(), "urgency", "score", "q", "t", nil, nil)
	if len(c.cache) != MaxEntries {
		t.Fatalf("cache size %d", len(c.cache))
	}
	// the oldest entry (i = 1999) must be gone, the new answer present
	_, key := sentKey("urgency", "score", "q", "t", nil, nil)
	if _, ok := c.cache[key]; !ok {
		t.Fatal("new entry missing")
	}
	k1999 := "k" + string(rune('a'+1999%26)) + strings.Repeat("x", 1999/26)
	if _, ok := c.cache[k1999]; ok {
		t.Fatal("oldest entry not evicted")
	}
}

func runCLI(t *testing.T, h *home.Home, args ...string) (string, string, int) {
	t.Helper()
	var out, errb bytes.Buffer
	env := cli.Env{Stdin: strings.NewReader(""), Stdout: &out, Stderr: &errb, Getenv: os.Getenv, Home: h}
	code := cli.Run(context.Background(), env, Commands(), append([]string{"jev"}, args...))
	return out.String(), errb.String(), code
}

func TestCIHintCLI(t *testing.T) {
	_, bin, h := setup(t, []fakebin.Rule{{Bin: "jev", Stdout: `{"choice":"flaky","probabilities":{"flaky":0.876,"real":0.124}}`}})
	f := filepath.Join(t.TempDir(), "log.txt")
	log := strings.Repeat("noise\n", 2000) + "ERROR 503 from mirror\n"
	os.WriteFile(f, []byte(log), 0o644)
	out, _, code := runCLI(t, h, "ci-hint", "--file", f)
	if code != 0 || strings.TrimSpace(out) != `{"hint":"flaky","probability":0.88,"status":"ok"}` {
		t.Fatalf("%d %q", code, out)
	}
	c := fakebin.Calls(t, bin)
	if len(c) != 1 || !strings.HasSuffix(c[0].Stdin, "ERROR 503 from mirror\n") || len([]rune(c[0].Stdin)) > MaxChars {
		t.Fatal("must send the tail of the log on stdin")
	}
	for _, a := range c[0].Args {
		if strings.Contains(a, "ERROR 503") {
			t.Fatal("text on argv")
		}
	}
}

func TestCIHintFallbacks(t *testing.T) {
	_, bin, h := setup(t, []fakebin.Rule{{Bin: "jev", Exit: 2}})
	dir := t.TempDir()
	empty := filepath.Join(dir, "empty")
	os.WriteFile(empty, []byte("  \n"), 0o644)
	full := filepath.Join(dir, "full")
	os.WriteFile(full, []byte("boom"), 0o644)
	tests := []struct{ name, file, want string }{
		{"missing file", filepath.Join(dir, "nope"), `{"hint":"none","probability":0,"status":"failed"}`},
		{"empty", empty, `{"hint":"none","probability":0,"status":"failed"}`},
		{"jev fails", full, `{"hint":"none","probability":0,"status":"failed"}`},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			out, _, code := runCLI(t, h, "ci-hint", "--file", tc.file)
			if code != 0 || strings.TrimSpace(out) != tc.want {
				t.Fatalf("%d %q", code, out)
			}
		})
	}
	// off keeps "off"; missing keeps "missing"
	os.WriteFile(filepath.Join(h.Root, "ui_settings.json"), []byte(`{"use_jev": false}`), 0o644)
	n := len(fakebin.Calls(t, bin))
	out, _, code := runCLI(t, h, "ci-hint", "--file", full)
	if code != 0 || strings.TrimSpace(out) != `{"hint":"none","probability":0,"status":"off"}` || len(fakebin.Calls(t, bin)) != n {
		t.Fatalf("off: %d %q", code, out)
	}
	os.WriteFile(filepath.Join(h.Root, "ui_settings.json"), []byte(`{}`), 0o644)
	t.Setenv("PATH", t.TempDir())
	out, _, _ = runCLI(t, h, "ci-hint", "--file", full)
	if strings.TrimSpace(out) != `{"hint":"none","probability":0,"status":"missing"}` {
		t.Fatalf("missing: %q", out)
	}
}

func TestFindingHintCLI(t *testing.T) {
	_, bin, h := setup(t, []fakebin.Rule{
		{Bin: "jev", StdinContains: "wrong one", Stdout: `{"choice":"rebut","probabilities":{"rebut":0.7}}`},
		{Bin: "jev", Stdout: `{"choice":"fix","confidence":0.55}`},
	})
	dir := t.TempDir()
	f := filepath.Join(dir, "f.json")
	os.WriteFile(f, []byte(`[{"id":"a","text":"real bug"},{"id":7,"text":"wrong one"},{"text":"no id"},{"id":"e","text":""},"junk"]`), 0o644)
	out, _, code := runCLI(t, h, "finding-hint", "--file", f)
	if code != 0 {
		t.Fatal(code)
	}
	var got []map[string]any
	if err := json.Unmarshal([]byte(out), &got); err != nil || len(got) != 5 {
		t.Fatalf("%v %q", err, out)
	}
	want := []string{`a/fix/0.55/ok`, `7/rebut/0.7/ok`, `#3/fix/0.55/ok`, `e/none/0/failed`, `#5/none/0/failed`}
	for i, g := range got {
		s := strings.Join([]string{fmtv(g["id"]), g["hint"].(string), fmtv(g["probability"]), g["status"].(string)}, "/")
		if s != want[i] {
			t.Fatalf("item %d = %s want %s", i, s, want[i])
		}
	}
	if len(fakebin.Calls(t, bin)) != 3 {
		t.Fatalf("calls %d", len(fakebin.Calls(t, bin)))
	}
	// unreadable / non-list -> []
	bad := filepath.Join(dir, "bad")
	os.WriteFile(bad, []byte(`{"a":1}`), 0o644)
	for _, p := range []string{bad, filepath.Join(dir, "nope")} {
		out, _, code = runCLI(t, h, "finding-hint", "--file", p)
		if code != 0 || strings.TrimSpace(out) != "[]" {
			t.Fatalf("%q %d", out, code)
		}
	}
	// more than 20 findings are cut to 20
	var many []string
	for i := 0; i < 30; i++ {
		many = append(many, `{"id":`+string(rune('0'+i%10))+`,"text":"x"}`)
	}
	big := filepath.Join(dir, "big")
	os.WriteFile(big, []byte("["+strings.Join(many, ",")+"]"), 0o644)
	out, _, _ = runCLI(t, h, "finding-hint", "--file", big)
	json.Unmarshal([]byte(out), &got)
	if len(got) != 20 {
		t.Fatalf("got %d", len(got))
	}
}

func fmtv(v any) string {
	b, _ := json.Marshal(v)
	return strings.Trim(string(b), `"`)
}

func TestCLIUsage(t *testing.T) {
	_, _, h := setup(t, nil)
	if _, _, code := runCLI(t, h, "ci-hint"); code != cli.ExitUsage {
		t.Fatal(code)
	}
	if _, _, code := runCLI(t, h, "bogus", "--file", "x"); code != cli.ExitUsage {
		t.Fatal(code)
	}
}
