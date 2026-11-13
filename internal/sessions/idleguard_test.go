package sessions

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/cli"
)

const idleBlockJSON = `{"decision":"block","reason":"Do not stop idle. Either continue the flow to its end, ask the user with ` + "`setu ask`" + ` and end your turn, or, when done, end with a very short table with check-mark emojis. Never call Monitor or ScheduleWakeup."}` + "\n"

func idleFixture(name string) string { return filepath.Join("testdata", "idle", name+".jsonl") }

func TestIdleDecide(t *testing.T) {
	cases := []struct {
		fixture, last string
		want          idleVerdict
	}{
		{"135-pass-table", "", idleBlock},
		{"check-table", "", idleAllow},
		{"135-pass-table", "| Step | Done |\n|---|---|\n| PR opened | ✔ |", idleAllow},
		{"135-pass-table", "No table, ✅ outside a row", idleBlock},
		{"bg-bash-live", "", idleAllow},
		{"bg-bash-ended", "", idleBlock},
		{"bg-agent-live", "", idleAllow},
		{"bg-agent-then-skill", "", idleAllow},
		{"monitor-only", "", idleBlock},
		{"prev-turn-bg", "", idleBlock},
		{"api-error", "", idleSkip},
	}
	for _, c := range cases {
		entries, err := readTurn(idleFixture(c.fixture))
		if err != nil {
			t.Fatal(err)
		}
		if got := decideIdle(hookInput{LastAssistantMessage: c.last}, entries); got != c.want {
			t.Errorf("%s (last %q): got %d, want %d", c.fixture, c.last, got, c.want)
		}
		// the pure decision over the whole file agrees with the tail read
		all, _ := os.ReadFile(idleFixture(c.fixture))
		var raws []json.RawMessage
		for _, l := range bytes.Split(bytes.TrimSpace(all), []byte{'\n'}) {
			raws = append(raws, l)
		}
		if got := decideIdle(hookInput{LastAssistantMessage: c.last}, raws); got != c.want {
			t.Errorf("%s whole file: got %d, want %d", c.fixture, got, c.want)
		}
	}
}

func TestIdleTaskStopEndsBackground(t *testing.T) {
	entries, err := readTurn(idleFixture("bg-bash-live"))
	if err != nil {
		t.Fatal(err)
	}
	stop := json.RawMessage(`{"type":"assistant","message":{"content":[{"type":"tool_use","id":"tu_s","name":"TaskStop","input":{"task_id":"bash_abc123"}}]}}`)
	if got := decideIdle(hookInput{}, append(entries, stop)); got != idleBlock {
		t.Fatalf("stopped task still allows: %d", got)
	}
}

func TestIdleReadTurnStopsAtTurnStart(t *testing.T) {
	entries, err := readTurn(idleFixture("prev-turn-bg"))
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 2 || !strings.Contains(string(entries[0]), "Answer to q-1") {
		t.Fatalf("%d entries: %s", len(entries), entries)
	}
}

// A 50 MB transcript is decided from its tail, well inside the 5 s budget.
func TestIdleLongTranscript(t *testing.T) {
	path := filepath.Join(t.TempDir(), "long.jsonl")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	line := []byte(`{"type":"assistant","message":{"content":[{"type":"text","text":"` + strings.Repeat("x", 4000) + `"}]}}` + "\n")
	for written := 0; written < 50<<20; written += len(line) {
		if _, err := f.Write(line); err != nil {
			t.Fatal(err)
		}
	}
	tail, _ := os.ReadFile(idleFixture("135-pass-table"))
	f.Write(tail)
	f.Close()
	began := time.Now()
	entries, err := readTurn(path)
	if err != nil {
		t.Fatal(err)
	}
	if got := decideIdle(hookInput{}, entries); got != idleBlock {
		t.Fatalf("got %d", got)
	}
	if d := time.Since(began); d > 5*time.Second || len(entries) != 4 {
		t.Fatalf("%d entries in %s", len(entries), d)
	}
}

func runHookCLI(t *testing.T, e *tenv, sid, stdin string) (int, string) {
	t.Helper()
	var out, errb bytes.Buffer
	env := cli.Env{Stdin: strings.NewReader(stdin), Stdout: &out, Stderr: &errb, Home: e.h,
		Getenv: func(k string) string { return map[string]string{"SETU_SESSION": sid}[k] }}
	code := cli.Run(context.Background(), env, Commands(), []string{"hook", "idle"})
	if errb.Len() > 0 {
		t.Fatalf("stderr: %q", errb.String())
	}
	return code, out.String()
}

func hookStdin(t *testing.T, fixture string) string {
	t.Helper()
	abs, err := filepath.Abs(idleFixture(fixture))
	if err != nil {
		t.Fatal(err)
	}
	b, _ := json.Marshal(hookInput{SessionID: "sx", TranscriptPath: abs})
	return string(b)
}

// Three stops in a row through the real binary: block, block, then allow and mark stalled.
func TestIdleHookThreeStops(t *testing.T) {
	e := newEnv(t)
	rec := newBareSession(t, e)
	other := newBareSession(t, e)
	t.Setenv("SESSIONS_TEST_AS_SETU", "1")
	stdin := hookStdin(t, "135-pass-table")
	for i, want := range []string{idleBlockJSON, idleBlockJSON, ""} {
		cmd := exec.Command(os.Args[0], "hook", "idle")
		cmd.Env = append(os.Environ(), "SETU_SESSION="+rec.ID)
		cmd.Stdin = strings.NewReader(stdin)
		out, err := cmd.Output()
		if err != nil || string(out) != want {
			t.Fatalf("stop %d: %v %q", i+1, err, out)
		}
		got, _ := readRecord(e.h, rec.ID)
		if i < 2 && (got.IdleBlocks != i+1 || got.Stalled != "") {
			t.Fatalf("stop %d: %+v", i+1, got)
		}
		if i == 2 && (got.IdleBlocks != 0 || got.Stalled != "ended without finishing or asking") {
			t.Fatalf("stop 3: blocks %d stalled %q", got.IdleBlocks, got.Stalled)
		}
	}
	if o, _ := readRecord(e.h, other.ID); o.IdleBlocks != 0 || o.Stalled != "" {
		t.Fatalf("counts mixed: %+v", o)
	}
}

func TestIdleHookAllows(t *testing.T) {
	e := newEnv(t)
	for _, fx := range []string{"check-table", "bg-bash-live", "bg-agent-live"} {
		rec := newBareSession(t, e)
		if _, out := runHookCLI(t, e, rec.ID, hookStdin(t, "135-pass-table")); out != idleBlockJSON {
			t.Fatalf("%s: setup block: %q", fx, out)
		}
		if code, out := runHookCLI(t, e, rec.ID, hookStdin(t, fx)); code != 0 || out != "" {
			t.Fatalf("%s: %d %q", fx, code, out)
		}
		if got, _ := readRecord(e.h, rec.ID); got.IdleBlocks != 0 || got.Stalled != "" {
			t.Fatalf("%s: not reset: %+v", fx, got)
		}
	}
}

func TestIdleHookPendingQuestionAllows(t *testing.T) {
	e := newEnv(t)
	rec := newBareSession(t, e)
	for range 2 {
		runHookCLI(t, e, rec.ID, hookStdin(t, "135-pass-table"))
	}
	if _, err := SetPending(e.h, rec.ID, json.RawMessage(askQ)); err != nil {
		t.Fatal(err)
	}
	// the transcript would block, and the count is used up, yet the question wins
	if code, out := runHookCLI(t, e, rec.ID, hookStdin(t, "135-pass-table")); code != 0 || out != "" {
		t.Fatalf("%d %q", code, out)
	}
	if got, _ := readRecord(e.h, rec.ID); got.Stalled != "" || got.IdleBlocks != 0 {
		t.Fatalf("%+v", got)
	}
}

func TestIdleHookAPIErrorKeepsCount(t *testing.T) {
	e := newEnv(t)
	rec := newBareSession(t, e)
	runHookCLI(t, e, rec.ID, hookStdin(t, "135-pass-table"))
	if code, out := runHookCLI(t, e, rec.ID, hookStdin(t, "api-error")); code != 0 || out != "" {
		t.Fatalf("%d %q", code, out)
	}
	if got, _ := readRecord(e.h, rec.ID); got.IdleBlocks != 1 || got.Stalled != "" {
		t.Fatalf("%+v", got)
	}
}

func TestIdleHookErrorsAllow(t *testing.T) {
	e := newEnv(t)
	rec := newBareSession(t, e)
	missing, _ := json.Marshal(hookInput{TranscriptPath: filepath.Join(t.TempDir(), "gone.jsonl")})
	// a directory cannot be read as a transcript, whoever runs the test (mode 0000 does not stop root)
	locked, _ := json.Marshal(hookInput{TranscriptPath: t.TempDir()})
	for name, c := range map[string][2]string{
		"no session":         {"", hookStdin(t, "135-pass-table")},
		"unknown session":    {"20990101T000000000000Z-deadbeef", hookStdin(t, "135-pass-table")},
		"invalid json":       {rec.ID, "not json"},
		"no transcript path": {rec.ID, `{}`},
		"missing transcript": {rec.ID, string(missing)},
		"unreadable":         {rec.ID, string(locked)},
	} {
		if code, out := runHookCLI(t, e, c[0], c[1]); code != 0 || out != "" {
			t.Errorf("%s: %d %q", name, code, out)
		}
	}
	if got, _ := readRecord(e.h, rec.ID); got.IdleBlocks != 0 || got.Stalled != "" {
		t.Fatalf("an error changed the record: %+v", got)
	}
	var errb bytes.Buffer
	if code := cli.Run(context.Background(), cli.Env{Stderr: &errb}, Commands(), []string{"hook", "nope"}); code != cli.ExitUsage || !strings.Contains(errb.String(), "usage: setu hook idle") {
		t.Fatalf("unknown hook: %d %q", code, errb.String())
	}
}
