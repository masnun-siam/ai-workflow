package dispatch

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net"
	"strings"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/cli"
	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

func runCLI(t *testing.T, h *home.Home, args ...string) (int, string, string) {
	t.Helper()
	var out, errb bytes.Buffer
	code := cli.Run(context.Background(), cli.Env{Stdout: &out, Stderr: &errb, Home: h, Getenv: func(string) string { return "" }}, Commands(), append([]string{"dispatch"}, args...))
	return code, out.String(), errb.String()
}

// cliHome is a test home whose server port is closed (the real one may be in use on this machine).
func cliHome(t *testing.T) *home.Home {
	t.Helper()
	return newEnv(t).h
}

func closePort(t *testing.T, h *home.Home) int {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := l.Addr().(*net.TCPAddr).Port
	l.Close()
	if err := home.WriteJSON(h.Path("ui_settings.json"), map[string]any{"server": map[string]any{"port": port}}); err != nil {
		t.Fatal(err)
	}
	return port
}

func saveD(t *testing.T, h *home.Home, d *store.Dispatch) {
	t.Helper()
	if err := store.Save(h, d); err != nil {
		t.Fatal(err)
	}
}

func TestCLIShapes(t *testing.T) {
	h := cliHome(t)
	epic := "o/r#1"
	d := &store.Dispatch{ID: "aaaaaaaaaaaa", Epic: &epic, Title: "T", Runner: "headless", State: store.Running, Settings: store.Defaults(), CreatedAt: 100,
		Lanes: map[string]*store.Lane{
			"o/r#2":  {Repo: "o/r", N: 2, Title: "two", Stage: store.StClosed, Deps: []string{}},
			"o/r#10": {Repo: "o/r", N: 10, Title: "ten ü", Stage: store.StImplementing, PR: 4, NeedsYou: "waiting on you", Deps: []string{}, Handle: &store.Handle{Session: "S1"}},
		}}
	saveD(t, h, d)
	lst := &store.Dispatch{ID: "bbbbbbbbbbbb", Title: "Small changes: #3", Runner: "headless", State: store.Done, Issues: []string{"o/r#3"}, Settings: store.Defaults(), CreatedAt: 50,
		Lanes: map[string]*store.Lane{"o/r#3": {Repo: "o/r", N: 3, Stage: store.StClosed, Deps: []string{}}}}
	saveD(t, h, lst)

	code, out, _ := runCLI(t, h, "ls")
	want := "aaaaaaaaaaaa  running    o/r#1                     1/2 closed  headless\n" +
		"bbbbbbbbbbbb  done       Small changes: #3         1/1 closed  headless\n"
	if code != 0 || out != want {
		t.Fatalf("%d %q", code, out)
	}

	code, out, _ = runCLI(t, h, "show", "aaaaaaaaaaaa")
	if code != 0 {
		t.Fatal(code)
	}
	var shown map[string]any
	if err := json.Unmarshal([]byte(out), &shown); err != nil {
		t.Fatal(err, out)
	}
	lanes := shown["lanes"].([]any)
	if shown["id"] != "aaaaaaaaaaaa" || shown["runner"] != "headless" || len(lanes) != 2 || lanes[0].(map[string]any)["n"] != float64(2) ||
		lanes[1].(map[string]any)["needs_you"] != "waiting on you" || lanes[1].(map[string]any)["pr"] != float64(4) {
		t.Fatal(out)
	}
	if !strings.Contains(out, "\n \"id\": \"aaaaaaaaaaaa\"") || !strings.Contains(out, `"title": "ten \u00fc"`) {
		t.Fatalf("python-style indent 1 and ensure_ascii: %s", out)
	}
	if code, _, errb := runCLI(t, h, "show", "ffffffffffff"); code != ExitInvalid || !strings.Contains(errb, "no dispatch ffffffffffff") {
		t.Fatal(code, errb)
	}
	if code, _, _ := runCLI(t, h, "show", "bad id"); code != ExitInvalid {
		t.Fatal(code)
	}

	// set: casts, prints the settings compactly
	code, out, errb := runCLI(t, h, "set", "aaaaaaaaaaaa", "max=3", "grind=simple", "auto_merge=on", "skip_approval=no", "max_cost=12.5", "model=opus")
	if code != 0 {
		t.Fatal(code, errb)
	}
	if !strings.HasPrefix(out, `{"max": 3, "grind": "simple", "ci": "wait", "auto_merge": true, "skip_approval": false, "feature_branch": null, "base_branch": null, "model": "opus", "effort": null, "account": null, "max_cost": 12.5}`) {
		t.Fatalf("%q", out)
	}
	code, out, _ = runCLI(t, h, "set", "aaaaaaaaaaaa", "max_cost=", "model=")
	if code != 0 || !strings.Contains(out, `"max_cost": null`) || !strings.Contains(out, `"model": null`) {
		t.Fatal(code, out)
	}
	for _, bad := range [][]string{{"set", "aaaaaaaaaaaa", "max=lots"}, {"set", "aaaaaaaaaaaa", "color=red"}, {"set", "aaaaaaaaaaaa", "max=0"}, {"set", "aaaaaaaaaaaa", "base_branch=x"}, {"set", "aaaaaaaaaaaa", "novalue"}} {
		if code, _, _ := runCLI(t, h, bad...); code != ExitInvalid {
			t.Errorf("%v: %d", bad, code)
		}
	}
	if code, _, _ := runCLI(t, h, "set", "aaaaaaaaaaaa"); code != cli.ExitUsage {
		t.Fatal("usage")
	}

	// lane by number or key; pause/resume/cancel words
	code, out, _ = runCLI(t, h, "lane", "aaaaaaaaaaaa", "10", "pause")
	if code != 0 || out != "o/r#10: pause\n" || !mustLoad(t, h).Lanes["o/r#10"].Paused {
		t.Fatal(code, out)
	}
	code, out, _ = runCLI(t, h, "lane", "aaaaaaaaaaaa", "o/r#10", "send", "hello there")
	if code != 0 || out != "o/r#10: send\n" {
		t.Fatal(code, out)
	}
	if code, _, _ := runCLI(t, h, "lane", "aaaaaaaaaaaa", "10", "dance"); code != ExitInvalid {
		t.Fatal(code)
	}
	// in order: resume after cancel would revive the dispatch
	for _, vw := range [][2]string{{"pause", "paused"}, {"resume", "resumed"}, {"cancel", "cancelled"}} {
		verb, word := vw[0], vw[1]
		code, out, _ = runCLI(t, h, verb, "aaaaaaaaaaaa")
		if code != 0 || out != word+"\n" {
			t.Errorf("%s: %d %q", verb, code, out)
		}
	}
	if mustLoad(t, h).State != store.Cancelled {
		t.Fatal("cancelled")
	}

	// retry-failed
	code, out, _ = runCLI(t, h, "retry-failed", "aaaaaaaaaaaa")
	if code != 0 || out != "o/r#10\n" {
		t.Fatal(code, out)
	}
	code, out, _ = runCLI(t, h, "retry-failed", "aaaaaaaaaaaa")
	if code != 0 || out != "nothing to retry\n" {
		t.Fatal(code, out)
	}

	// end
	if code, _, _ := runCLI(t, h, "end", "aaaaaaaaaaaa", "open-pr"); code != ExitInvalid {
		t.Fatal("no feature branch")
	}
	if code, _, _ := runCLI(t, h, "end", "bbbbbbbbbbbb", "qa"); code != ExitInvalid {
		t.Fatal("issue lists refuse end actions")
	}
	d2 := mustLoad(t, h)
	d2.Settings.FeatureBranch = store.Ptr("feat")
	saveD(t, h, &d2)
	code, out, _ = runCLI(t, h, "end", "aaaaaaaaaaaa", "open-pr")
	if code != 0 || out != "open-pr: requested; the UI server runs it at its next tick\n" {
		t.Fatal(code, out)
	}

	// unknown verb / no verb
	if code, _, _ := runCLI(t, h, "frobnicate"); code != cli.ExitUsage {
		t.Fatal(code)
	}
	if code, _, _ := runCLI(t, h); code != cli.ExitUsage {
		t.Fatal(code)
	}
}

func mustLoad(t *testing.T, h *home.Home) store.Dispatch {
	t.Helper()
	d, err := store.Load(h, "aaaaaaaaaaaa")
	if err != nil {
		t.Fatal(err)
	}
	return d
}

func TestCLIDoctorAndArchive(t *testing.T) {
	h := cliHome(t)
	closePort(t, h)
	CLIStartCalls := 0
	_ = CLIStartCalls
	d := &store.Dispatch{ID: "aaaaaaaaaaaa", Title: "T", Runner: "headless", State: store.Running, Settings: store.Defaults(), CreatedAt: 100, Lanes: map[string]*store.Lane{
		"o/r#1": {Repo: "o/r", N: 1, Stage: store.StSkipped, SkipReason: "needs refine", Deps: []string{}},
		"o/r#2": {Repo: "o/r", N: 2, Stage: store.StQueued, Deps: []string{"o/r#1"}},
	}}
	saveD(t, h, d)
	done := &store.Dispatch{ID: "bbbbbbbbbbbb", Title: "D", Runner: "headless", State: store.Done, Settings: store.Defaults(), CreatedAt: 1, EndedAt: 2, Lanes: map[string]*store.Lane{}}
	saveD(t, h, done)

	// the server port is closed in tests: doctor adds the dead-server line and exits 1
	code, out, _ := runCLI(t, h, "doctor")
	lines := strings.Split(strings.TrimSpace(out), "\n")
	if code != ExitProblem || len(lines) != 2 || lines[0] != "aaaaaaaaaaaa  -  dead server: nothing ticks this dispatch (run `setu serve`)" ||
		lines[1] != "aaaaaaaaaaaa  o/r#2  blocked by skipped #1" {
		t.Fatalf("%d %q", code, out)
	}
	// a clean dispatch prints ok and exits 0 once the server is "up"
	clean := mustLoad(t, h)
	clean.Lanes = map[string]*store.Lane{"o/r#5": {Repo: "o/r", N: 5, Stage: store.StImplementing, Deps: []string{}}}
	clean.State = store.Cancelled
	saveD(t, h, &clean)
	if code, out, _ = runCLI(t, h, "doctor", "aaaaaaaaaaaa"); code != 0 || out != "aaaaaaaaaaaa  ok\n" && out != "" {
		t.Fatalf("%d %q", code, out)
	}
	if code, _, _ := runCLI(t, h, "doctor", "ffffffffffff"); code != ExitInvalid {
		t.Fatal(code)
	}

	// archive --days
	code, out, _ = runCLI(t, h, "archive", "--days", "0")
	if code != 0 || out != "aaaaaaaaaaaa\nbbbbbbbbbbbb\n" && out != "bbbbbbbbbbbb\naaaaaaaaaaaa\n" {
		t.Fatalf("%d %q", code, out)
	}
	if code, out, _ = runCLI(t, h, "archive"); code != 0 || out != "" {
		t.Fatal(code, out)
	}
	if code, _, _ := runCLI(t, h, "archive", "--days", "x"); code != cli.ExitUsage {
		t.Fatal(code)
	}
}

func TestWatch(t *testing.T) {
	h := cliHome(t)
	closePort(t, h)
	base := time.Unix(1_000_000, 0)
	var slept int
	clk := base
	d := &store.Dispatch{ID: "aaaaaaaaaaaa", Title: "T", Runner: "headless", State: store.Running, Settings: store.Defaults(), CreatedAt: 1, Lanes: map[string]*store.Lane{},
		Events: []store.Event{{At: 5, Kind: "stage", Text: "old"}}}
	saveD(t, h, d)
	var starts int
	hk := WatchHooks{
		Up:    func() bool { return false },
		Start: func() { starts++ },
		Sleep: func(dur time.Duration) {
			slept++
			clk = clk.Add(dur)
			if slept == 3 { // an event that needs the user lands
				cur, _ := store.Load(h, "aaaaaaaaaaaa")
				cur.AddEvent("o/r#1", "stage", "queued -> implementing", 20)
				cur.AddEvent("o/r#1", "needs_you", "waiting on you", 21)
				_ = store.Save(h, &cur)
			}
		},
		Clock: func() time.Time { return clk },
	}
	evs, state, err := Watch(h, "aaaaaaaaaaaa", 10, 3000, 10, hk)
	if err != nil || state != "running" || len(evs) != 2 || evs[1].Kind != "needs_you" || slept != 3 {
		t.Fatal(evs, state, err, slept)
	}
	if starts != 1 {
		t.Fatalf("the server is restarted at most once per 60 s: %d", starts)
	}
	// timeout returns what there is
	clk = base
	slept = 0
	hk.Sleep = func(dur time.Duration) { slept++; clk = clk.Add(dur) }
	evs, state, err = Watch(h, "aaaaaaaaaaaa", 100, 25, 10, hk)
	if err != nil || len(evs) != 0 || slept != 3 {
		t.Fatal(evs, err, slept)
	}
	// a finished dispatch returns at once
	cur, _ := store.Load(h, "aaaaaaaaaaaa")
	cur.State = store.Done
	_ = store.Save(h, &cur)
	slept = 0
	if _, state, _ = Watch(h, "aaaaaaaaaaaa", 100, 3000, 10, hk); state != "done" || slept != 0 {
		t.Fatal(state, slept)
	}
	if _, _, err := Watch(h, "ffffffffffff", 0, 1, 1, hk); err == nil {
		t.Fatal("missing")
	}

	// the verb prints `HH:MM  lane  kind  text` then state/since
	code, out, _ := runCLI(t, h, "watch", "aaaaaaaaaaaa", "--since", "0", "--timeout", "1")
	if code != 0 {
		t.Fatal(code)
	}
	ls := strings.Split(strings.TrimSpace(out), "\n")
	if len(ls) != 4 || !strings.HasSuffix(ls[2], "needs_you       waiting on you") || ls[3] != "state=done since=21.0" {
		t.Fatalf("%q", out)
	}
	if !strings.Contains(ls[0], "-                     stage           old") {
		t.Fatalf("%q", ls[0])
	}
}

func TestCLIPlanAndStart(t *testing.T) {
	e := newEnv(t)
	port := closePort(t, e.h)
	bin := t.TempDir()
	fakebin.Install(t, bin)
	epicJSON := fmt.Sprintf(`{"data":{"repository":{"issue":{"title":"The epic","subIssues":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":[%s,%s]}}}}}`,
		nodeJSON(node{n: 2, state: "OPEN", refined: true}), nodeJSON(node{n: 3, state: "OPEN", refined: false, blocked: []string{"o/r#2:OPEN"}}))
	fakebin.WriteRules(t, bin, []fakebin.Rule{
		{Bin: "gh", ArgsPrefix: []string{"api", "graphql"}, ArgsContains: "subIssues", Stdout: epicJSON},
		{Bin: "jev", Exit: 1},
	})
	CLIGrind = nil
	var started int
	old := CLIStart
	CLIStart = func(*home.Home) error { started++; return nil }
	defer func() { CLIStart = old }()

	code, out, errb := runCLI(t, e.h, "plan", "o/r#1", "--max", "3", "--ci=defer", "--auto-merge")
	if code != 0 {
		t.Fatal(code, errb)
	}
	var p map[string]any
	if err := json.Unmarshal([]byte(out), &p); err != nil {
		t.Fatal(err, out)
	}
	if p["title"] != "The epic" || p["settings"].(map[string]any)["max"] != float64(3) || p["settings"].(map[string]any)["ci"] != "defer" || p["settings"].(map[string]any)["auto_merge"] != true ||
		len(p["lanes"].([]any)) != 2 || len(p["waves"].([]any)) != 1 {
		t.Fatal(out)
	}
	if len(store.List(e.h)) != 0 {
		t.Fatal("plan changes nothing")
	}

	code, out, errb = runCLI(t, e.h, "start", "o/r#1", "--grind", "off")
	if code != 0 {
		t.Fatal(code, errb)
	}
	ds := store.List(e.h)
	if len(ds) != 1 || started != 1 {
		t.Fatalf("%d dispatches, server started %d times", len(ds), started)
	}
	var st struct {
		ID    string  `json:"id"`
		Lanes int     `json:"lanes"`
		Since float64 `json:"since"`
		UI    string  `json:"ui"`
	}
	if err := json.Unmarshal([]byte(out), &st); err != nil || st.ID != ds[0].ID || st.Lanes != 2 || st.Since != ds[0].CreatedAt || st.UI != fmt.Sprintf("http://127.0.0.1:%d", port) {
		t.Fatalf("%q %+v", out, st)
	}
	if !strings.HasPrefix(out, fmt.Sprintf(`{"id": "%s", "lanes": 2, "since": `, ds[0].ID)) {
		t.Fatalf("python-style compact json: %q", out)
	}
	if ds[0].Settings.Grind != "off" {
		t.Fatal("flags reach the settings")
	}
	// the same epic again is refused (exit 5), nothing new is saved
	if code, _, errb := runCLI(t, e.h, "start", "o/r#1"); code != ExitInvalid || !strings.Contains(errb, "is already a lane of dispatch") {
		t.Fatal(code, errb)
	}
	// usage errors
	for _, bad := range [][]string{{"plan"}, {"plan", "o/r#1", "--bogus", "1"}, {"plan", "o/r#1", "--max", "x"}, {"start", "o/r#1", "--runner", "herdr"}, {"plan", "a", "b"}} {
		if code, _, _ := runCLI(t, e.h, bad...); code != cli.ExitUsage {
			t.Errorf("%v: %d", bad, code)
		}
	}
	if code, _, _ := runCLI(t, e.h, "plan", "o/r#1", "--max", "99"); code != ExitInvalid {
		t.Fatal("bad value")
	}
}

func TestPyDump(t *testing.T) {
	cases := []struct {
		in     any
		indent int
		want   string
	}{
		{map[string]any{"a": 1, "b": "x, y: z"}, 0, `{"a": 1, "b": "x, y: z"}`},
		{[]any{1, "é", "😀"}, 0, `[1, "\u00e9", "\ud83d\ude00"]`},
		{map[string]any{"a": []int{1}}, 1, "{\n \"a\": [\n  1\n ]\n}"},
		{map[string]any{"q": `he said "hi, there"`}, 0, `{"q": "he said \"hi, there\""}`},
	}
	for _, c := range cases {
		if got := pyDump(c.in, c.indent); got != c.want {
			t.Errorf("got %q want %q", got, c.want)
		}
	}
	if pyFloat(3) != "3.0" || pyFloat(3.25) != "3.25" {
		t.Fatal("pyFloat")
	}
}
