package sessions

import (
	"context"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

var base = []string{"--print", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"}

func cat(parts ...[]string) []string {
	var out []string
	for _, p := range parts {
		out = append(out, p...)
	}
	return out
}

func TestGoldenArgvStart(t *testing.T) {
	ctx := context.Background()
	prompt := Prompt{Step: "implement-issue", Display: "/blubird:implement-issue 1", Text: "/blubird:implement-issue 1"}
	for _, tc := range []struct {
		name string
		spec Spec
		want []string
	}{
		{"plain", Spec{}, cat(base, []string{"/blubird:implement-issue 1"})},
		{"gated", Spec{Gate: true}, cat(base, []string{"--append-system-prompt", Headless, "/blubird:implement-issue 1"})},
		{"gated run model effort", Spec{Gate: true, RunModel: "opus", RunEffort: "high"},
			cat(base, []string{"--append-system-prompt", Headless, "--model", "opus", "--effort", "high", "/blubird:implement-issue 1"})},
		{"instructions only", Spec{Instructions: []string{"REENTRY"}}, cat(base, []string{"--append-system-prompt", "REENTRY", "/blubird:implement-issue 1"})},
		{"gate plus instructions", Spec{Gate: true, Instructions: []string{"REENTRY"}},
			cat(base, []string{"--append-system-prompt", Headless + "\n\nREENTRY", "/blubird:implement-issue 1"})},
		{"allowed tools", Spec{AllowedTools: []string{"Read", "Bash(git status:*)"}},
			[]string{"--print", "--output-format", "stream-json", "--verbose", "--allowedTools", "Read,Bash(git status:*)", "/blubird:implement-issue 1"}},
		{"dispatch lane", Spec{Gate: true, Effort: "high", Model: "opus"},
			cat(base, []string{"--append-system-prompt", Headless, "--effort", "high", "--model", "opus", "/blubird:implement-issue 1"})},
		{"answerer", Spec{AllowedTools: []string{"Read"}, Agent: "away-answerer", Model: "opus", RunEffort: "medium"},
			[]string{"--print", "--output-format", "stream-json", "--verbose", "--allowedTools", "Read", "--append-system-prompt", "AWAYBODY", "--model", "opus", "--effort", "medium", "/blubird:implement-issue 1"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			e := newEnv(t)
			e.claudeRule("--print", e.file("ok.jsonl", okStream("s1", 0.1, 1, 1)), 0)
			tc.spec.Prompt, tc.spec.Cwd = prompt, "acme/app"
			rec, err := e.m.Launch(ctx, tc.spec)
			mustNoErr(t, err)
			e.status(rec.ID, StDone)
			if got := e.lastClaude().Args; !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("argv\n got %q\nwant %q", got, tc.want)
			}
		})
	}
}

func TestEnvAndCwd(t *testing.T) {
	e := newEnv(t)
	out := filepath.Join(e.fb, "env.txt")
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: "--print", Exec: []string{"sh", "-c", "env > " + out + "; pwd >> " + out + "; cat " + filepath.Join(e.fb, "ok.jsonl")}})
	e.file("ok.jsonl", okStream("s1", 0.1, 1, 1))
	rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "7"))
	mustNoErr(t, err)
	e.status(rec.ID, StDone)
	b, _ := os.ReadFile(out)
	env := string(b)
	for _, want := range []string{"SETU_SESSION=" + rec.ID, "AIW_UI_SESSION=" + rec.ID, "SETU_HOME=" + e.h.Root, "BLUBIRD_IDLE_GUARD=off", e.repo} {
		if !strings.Contains(env, want) {
			t.Errorf("env lacks %q", want)
		}
	}
	if strings.Contains(env, "CLAUDE_PLUGIN_DATA") {
		t.Error("CLAUDE_PLUGIN_DATA leaked into the child")
	}
	if !strings.Contains(env, "PATH="+e.fb+":") {
		t.Error("PATH does not start with the setu bin dir")
	}
	// the child is its own session and process group; the record keeps the pid and fingerprint
	got, _ := e.m.Get(rec.ID)
	if got.PID == 0 || got.PidStarted == "" || got.SessionID != "s1" || got.Model != "claude-opus-5-5" {
		t.Errorf("record: %+v", got)
	}
	if got.Link == nil || got.Link.Issue != 7 || got.Link.Owner != "acme" {
		t.Errorf("link: %+v", got.Link)
	}
}

func TestDoneAccumulatesCostAndTokens(t *testing.T) {
	e := newEnv(t)
	e.claudeRule("--resume", e.file("second.jsonl", jl(initEv("s1"), resultEv(0.5, 4, 6, nil))), 0)
	e.claudeRule("--print", e.file("first.jsonl", okStream("s1", 0.25, 10, 5)), 0)
	rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "7"))
	mustNoErr(t, err)
	r1 := e.status(rec.ID, StDone)
	if r1.Cost == nil || *r1.Cost != 0.25 || r1.Tokens == nil || *r1.Tokens != (Tokens{10, 0, 5}) {
		t.Fatalf("first run: cost=%v tokens=%v", r1.Cost, r1.Tokens)
	}
	e.settled(rec.ID)
	state, err := e.m.SendPrompt(context.Background(), rec.ID, "more please", 4000)
	mustNoErr(t, err)
	if state != "sent" {
		t.Fatal(state)
	}
	r2 := e.wait(rec.ID, func(r Record) bool { return r.Status == StDone && r.Cost != nil && *r.Cost > 0.3 })
	if *r2.Cost != 0.75 || *r2.Tokens != (Tokens{14, 0, 11}) {
		t.Fatalf("accumulated: cost=%v tokens=%v", *r2.Cost, *r2.Tokens)
	}
	cl := e.lastClaude().Args
	want := cat(base, []string{"--append-system-prompt", Headless, "--resume", "s1", "more please"})
	if !reflect.DeepEqual(cl, want) {
		t.Fatalf("resume argv\n got %q\nwant %q", cl, want)
	}
}

func TestFailedExitCodeAndStderr(t *testing.T) {
	e := newEnv(t)
	e.claudeRule("--print", e.file("partial.jsonl", jl(initEv("s2"), textEv("working"))), 3)
	rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "9"))
	mustNoErr(t, err)
	r := e.status(rec.ID, StFailed)
	if r.Error != "claude exited with code 3; see stderr.log" || r.EndedAt == "" {
		t.Fatalf("%+v", r)
	}
	if e.notes.count("failed") != 1 {
		t.Fatalf("failed notifications: %d", e.notes.count("failed"))
	}
}

func TestLimitedByEventAndByRegex(t *testing.T) {
	reset := time.Now().Add(2 * time.Hour).Unix()
	errRes := resultEv(0, 0, 0, obj{"is_error": true, "result": "x", "errors": []any{"anything"}})
	for _, tc := range []struct {
		name   string
		stream string
		auto   bool
		resets int64
	}{
		{"event", jl(initEv("s3"), obj{"type": "rate_limit_event", "rate_limit_info": obj{"status": "rejected", "resetsAt": reset, "rateLimitType": "five_hour"}}, errRes), true, reset},
		{"regex", jl(initEv("s3"), resultEv(0, 0, 0, obj{"is_error": true, "result": "Claude usage limit reached", "usage": nil})), false, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			e := newEnv(t)
			e.claudeRule("--print", e.file("lim.jsonl", tc.stream), 1)
			rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "9"))
			mustNoErr(t, err)
			r := e.status(rec.ID, StLimited)
			if r.AutoResume == nil || *r.AutoResume != tc.auto || r.LimitResetsAt != tc.resets {
				t.Fatalf("%+v", r)
			}
			if tc.auto && r.LimitType != "five_hour" {
				t.Fatal(r.LimitType)
			}
			if got := e.m.Limits()["claude"].LimitedUntil; got != tc.resets {
				t.Fatalf("limits: %v", e.m.Limits())
			}
			// a new start on the limited account queues instead of spawning
			before := len(e.claudeCalls())
			if tc.auto {
				q, err := e.m.StartSession(context.Background(), e.req("refine-issues", "3"))
				mustNoErr(t, err)
				if q.Status != StLimited || q.Note != "queued: account is rate limited" || len(e.claudeCalls()) != before {
					t.Fatalf("queued start: %+v", q)
				}
			}
		})
	}
}

func TestLimitedResumeAfterReset(t *testing.T) {
	e := newEnv(t)
	e.m.stagger = time.Millisecond
	past := time.Now().Add(-time.Minute).Unix()
	e.claudeRule("--resume", e.file("second.jsonl", okStream("s4", 0.1, 1, 1)), 0)
	e.claudeRule("--print", e.file("lim.jsonl", jl(initEv("s4"), obj{"type": "rate_limit_event", "rate_limit_info": obj{"status": "rejected", "resetsAt": past, "rateLimitType": "five_hour"}},
		resultEv(0, 0, 0, obj{"is_error": true, "errors": []any{"limit"}}))), 1)
	a, err := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
	mustNoErr(t, err)
	e.status(a.ID, StLimited)
	e.settled(a.ID)
	// limit is in the past: a tick resumes it with the continue prompt
	e.m.limitTick(context.Background())
	e.status(a.ID, StDone)
	got := e.lastClaude().Args
	if got[len(got)-1] != continuePrompt || got[len(got)-3] != "--resume" || got[len(got)-2] != "s4" {
		t.Fatalf("argv %q", got)
	}
}

func TestBatchCapAndRelease(t *testing.T) {
	e := newEnv(t)
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: "--print", Exec: []string{"sh", "-c", "sleep 1; cat " + filepath.Join(e.fb, "ok.jsonl")}})
	e.file("ok.jsonl", okStream("sb", 0, 1, 1))
	var ids []string
	for i := 0; i < 4; i++ {
		req := e.req("implement-issue", string(rune('1'+i)))
		req.Batch = "b1"
		rec, err := e.m.StartSession(context.Background(), req)
		mustNoErr(t, err)
		ids = append(ids, rec.ID)
	}
	recs := make([]Record, 4)
	for i, id := range ids {
		recs[i], _ = e.m.Get(id)
	}
	if recs[3].Status != StQueued || recs[3].Note != "queued: 3 of this batch run at once" || recs[0].Status == StQueued {
		t.Fatalf("statuses: %v %v %v %v", recs[0].Status, recs[1].Status, recs[2].Status, recs[3].Status)
	}
	// the queued one starts when a slot frees
	e.wait(ids[3], func(r Record) bool { return r.Status == StDone })
}

func TestStopKillsProcessGroup(t *testing.T) {
	e := newEnv(t)
	pidFile := filepath.Join(e.fb, "child.pid")
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: "--print", Exec: []string{"sh", "-c", "sleep 300 & echo $! > " + pidFile + "; wait"}})
	rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
	mustNoErr(t, err)
	e.wait(rec.ID, func(r Record) bool { _, err := os.Stat(pidFile); return r.Status == StRunning && err == nil })
	time.Sleep(100 * time.Millisecond)
	if cur, _ := e.m.Get(rec.ID); cur.PID == 0 {
		t.Fatal("no pid")
	} else if pg, err := syscall.Getpgid(cur.PID); err != nil || pg != cur.PID {
		t.Fatalf("child is not its own process-group leader: pgid %d pid %d (%v)", pg, cur.PID, err)
	}
	out, err := e.m.Stop(context.Background(), rec.ID)
	mustNoErr(t, err)
	if out.Status != StStopped {
		t.Fatalf("%+v", out)
	}
	b, _ := os.ReadFile(pidFile)
	pid := strings.TrimSpace(string(b))
	if r := runPS(pid); r {
		t.Fatalf("grandchild %s survived", pid)
	}
	e.settled(rec.ID)
	got, _ := e.m.Get(rec.ID)
	if got.Status != StStopped {
		t.Fatalf("follower overwrote stopped: %v", got.Status)
	}
}

func TestHoldQueuedPrompt(t *testing.T) {
	e := newEnv(t)
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: "--resume", StdoutFile: e.file("two.jsonl", okStream("sh", 0.1, 1, 1))})
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: "--print", Exec: []string{"sh", "-c", "sleep 0.4; cat " + filepath.Join(e.fb, "one.jsonl")}})
	e.file("one.jsonl", okStream("sh", 0.1, 1, 1))
	rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
	mustNoErr(t, err)
	e.status(rec.ID, StRunning)
	_, err = e.m.Hold(rec.ID)
	mustNoErr(t, err)
	state, err := e.m.SendPrompt(context.Background(), rec.ID, "follow up", 4000)
	mustNoErr(t, err)
	if state != "queued" {
		t.Fatal(state)
	}
	e.status(rec.ID, StDone)
	e.settled(rec.ID)
	if n := len(e.claudeCalls()); n != 1 {
		t.Fatalf("held session was resumed: %d calls", n)
	}
	if _, err := e.m.Release(rec.ID); err != nil {
		t.Fatal(err)
	}
	e.wait(rec.ID, func(r Record) bool { return len(e.claudeCalls()) == 2 && r.Status == StDone && r.QueuedPrompt == "" })
	got := e.lastClaude().Args
	if got[len(got)-1] != "follow up" {
		t.Fatalf("%q", got)
	}
	if _, err := e.m.Release(rec.ID); kind(err) != "conflict" {
		t.Fatalf("release of unheld: %v", err)
	}
}

func TestPreflightAndSpawnFailures(t *testing.T) {
	e := newEnv(t)
	e.claude.preflightErr = os.ErrNotExist
	rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
	if kind(err) != "upstream" {
		t.Fatalf("err = %v", err)
	}
	got, _ := e.m.Get(rec.ID)
	if got.Status != StFailed || got.Error == "" || got.EndedAt == "" {
		t.Fatalf("%+v", got)
	}
}

func TestReapAfterAskedExit(t *testing.T) {
	e := newEnv(t)
	e.m.grace = 200 * time.Millisecond
	t.Setenv("SESSIONS_TEST_AS_SETU", "1")
	stream := jl(initEv("sr"), toolEv("Bash", obj{"command": "setu ask --json '{}'"}), resultEv(0.1, 1, 1, nil))
	q := `{"questions":[{"header":"h","question":"Which?","options":[{"label":"A"},{"label":"B"}]}]}`
	e.file("ask.jsonl", stream)
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: "--print", Exec: []string{"sh", "-c",
		"cat " + filepath.Join(e.fb, "ask.jsonl") + "; " + os.Args[0] + " ask --json '" + q + "'; sleep 300"}})
	rec, err := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
	mustNoErr(t, err)
	r := e.wait(rec.ID, func(r Record) bool { return r.Status == StWaiting && r.EndedAt != "" })
	if r.PendingQuestion == nil || r.PendingQuestion.Questions[0].Question != "Which?" {
		t.Fatalf("%+v", r.PendingQuestion)
	}
	e.settled(rec.ID) // the follower SIGTERMed the lingering process group
	if e.notes.count("waiting") != 1 {
		t.Fatalf("waiting notifications: %d", e.notes.count("waiting"))
	}
}

func runPS(pid string) bool {
	return exec_ps(pid)
}
