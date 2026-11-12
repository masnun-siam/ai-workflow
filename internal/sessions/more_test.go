package sessions

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/events"
)

func TestResumeAgentSessionArgv(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	e.claudeRule("--resume", e.file("r.jsonl", okStream("sa", 0, 1, 1)), 0)
	e.claudeRule("--print", e.file("f.jsonl", okStream("sa", 0, 1, 1)), 0)
	rec, err := e.m.Launch(ctx, Spec{Prompt: Prompt{Display: "Answer the round", Text: "Answer the round"}, Cwd: "acme/app", Gate: false,
		Agent: "away-answerer", AllowedTools: []string{"Read", "Bash(git status:*)"}, Model: "opus", RunEffort: "medium", Kind: "away"})
	mustNoErr(t, err)
	e.status(rec.ID, StDone)
	e.settled(rec.ID)
	want := []string{"--print", "--output-format", "stream-json", "--verbose", "--allowedTools", "Read,Bash(git status:*)",
		"--append-system-prompt", "AWAYBODY", "--model", "opus", "--effort", "medium", "Answer the round"}
	if got := e.lastClaude().Args; !reflect.DeepEqual(got, want) {
		t.Fatalf("start\n got %q\nwant %q", got, want)
	}
	mustNoErr(t, e.m.Resume(ctx, rec.ID, "again"))
	e.wait(rec.ID, func(r Record) bool { return len(e.claudeCalls()) == 2 && r.Status == StDone })
	// the direct --model is not re-added; the agent body rides in the one append value with Headless
	want = []string{"--print", "--output-format", "stream-json", "--verbose", "--allowedTools", "Read,Bash(git status:*)",
		"--append-system-prompt", "AWAYBODY\n\n" + Headless, "--effort", "medium", "--resume", "sa", "again"}
	if got := e.lastClaude().Args; !reflect.DeepEqual(got, want) {
		t.Fatalf("resume\n got %q\nwant %q", got, want)
	}
	if got, _ := e.m.Get(rec.ID); got.Kind != "away" || got.Agent != "away-answerer" {
		t.Fatalf("%+v", got)
	}
}

func TestMetaWatcherSeesAskFromAnotherProcess(t *testing.T) {
	e := newEnv(t)
	rec := newBareSession(t, e)
	ch, cancel := e.bus.Subscribe(16)
	defer cancel()
	if code, _, errs := runAskCLI(t, e, rec.ID, "--json", askQ); code != 0 {
		t.Fatal(errs)
	}
	e.m.watchMeta()
	e.m.watchMeta() // a second look finds nothing new
	if e.notes.count("waiting") != 1 {
		t.Fatalf("waiting notifications: %d", e.notes.count("waiting"))
	}
	var got bool
drain:
	for {
		select {
		case ev := <-ch:
			if ev.Topic == events.TSessions {
				if m, ok := ev.Data.(map[string]any); ok && m["id"] == rec.ID && m["status"] == StWaiting {
					got = true
				}
			}
		default:
			break drain
		}
	}
	if !got {
		t.Fatal("no sessions event for the ask")
	}
	// the loop does the same by itself
	rec2 := newBareSession(t, e)
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	e.m.Start(ctx)
	runAskCLI(t, e, rec2.ID, "--json", askQ)
	deadline := time.Now().Add(5 * time.Second)
	for e.notes.count("waiting") < 2 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if e.notes.count("waiting") != 2 {
		t.Fatalf("meta watcher loop did not notify: %d", e.notes.count("waiting"))
	}
}

// Updates from the server and a `setu ask` in another process lose no write.
func TestConcurrentUpdatesWithAsk(t *testing.T) {
	e := newEnv(t)
	rec := newBareSession(t, e)
	var wg sync.WaitGroup
	for i := 0; i < 25; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := e.m.Update(rec.ID, func(r *Record) error { r.Hooks++; return nil })
			if err != nil {
				t.Error(err)
			}
		}()
	}
	for i := 0; i < 5; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); runAskCLI(t, e, rec.ID, "--json", askQ) }()
	}
	wg.Wait()
	got, _ := e.m.Get(rec.ID)
	if got.Hooks != 25 || got.Status != StWaiting || got.PendingQuestion == nil {
		t.Fatalf("hooks %d status %s", got.Hooks, got.Status)
	}
}

func TestRateLimitWarningSurfaces(t *testing.T) {
	e := newEnv(t)
	future := time.Now().Add(time.Hour).Unix()
	e.claudeRule("--print", e.file("w.jsonl", jl(initEv("sw"),
		obj{"type": "rate_limit_event", "rate_limit_info": obj{"status": "allowed_warning", "resetsAt": future, "rateLimitType": "five_hour", "utilization": 0.91}},
		resultEv(0.1, 1, 1, nil))), 0)
	rec, _ := e.m.StartSession(context.Background(), e.req("implement-issue", "1"))
	e.status(rec.ID, StDone) // a warning is not a rejection
	w := e.m.Limits()["claude"].Warning
	if w == nil || w.Type != "five_hour" || w.Utilization == nil || *w.Utilization != 0.91 {
		t.Fatalf("%+v", e.m.Limits())
	}
}

func TestAfterStartFailureStopsSession(t *testing.T) {
	e := newEnv(t)
	e.slow("5")
	e.m.d.AfterStart = func(ctx context.Context, rec Record, req StartRequest) error { return errors.New("panel failed") }
	req := e.req("implement-issue", "1")
	req.Lenses = []string{"security"}
	rec, err := e.m.StartSession(context.Background(), req)
	if err == nil || err.Error() != "panel failed" {
		t.Fatalf("%v", err)
	}
	e.status(rec.ID, StStopped)
}

func TestStatsAndTitle(t *testing.T) {
	e := newEnv(t)
	e.m.d.Title = func(slug string, n int) string { return "Fix the thing" }
	r1, _ := e.m.create(Record{Command: "/blubird:implement-issue 5\nmore", Repo: e.repo, CwdPath: e.repo, Status: StDone, ClaudeCmd: "claude", Link: &Link{"acme", "app", 5}})
	c := 1.25
	e.m.Update(r1.ID, func(r *Record) error { r.Cost = &c; return nil })
	if s := e.m.Stats(); s.TodayCount != 1 || s.TodayCost != 1.25 || s.MonthCount != 1 {
		t.Fatalf("%+v", s)
	}
	pub := e.m.Public(mustGet(t, e, r1.ID))
	if pub.Title != "Fix the thing" || pub.DurationS == nil {
		t.Fatalf("%+v", pub)
	}
	r2, _ := e.m.create(Record{Command: "free text\nsecond line", Repo: e.repo, CwdPath: e.repo, Status: StDone, ClaudeCmd: "claude"})
	if p := e.m.Public(mustGet(t, e, r2.ID)); p.Title != "free text" || p.ResumeCommand != nil {
		t.Fatalf("%+v", p)
	}
	e.m.Update(r2.ID, func(r *Record) error { r.SessionID = "it's"; return nil })
	if p := e.m.Public(mustGet(t, e, r2.ID)); p.ResumeCommand == nil || *p.ResumeCommand != "cd "+shellQuote(e.repo)+" && claude --resume 'it'\"'\"'s'" {
		t.Fatalf("%v", *p.ResumeCommand)
	}
}

func mustGet(t *testing.T, e *tenv, id string) Record {
	t.Helper()
	r, err := e.m.Get(id)
	mustNoErr(t, err)
	return r
}

func TestCorruptMetaIsSkippedAndInvalidIDRejected(t *testing.T) {
	e := newEnv(t)
	good := newBareSession(t, e)
	id := "20260101T120000123456Z-0a1b2c3d"
	os.MkdirAll(sessionDir(e.h, id), 0o755)
	os.WriteFile(filepath.Join(sessionDir(e.h, id), "meta.json"), []byte("{not json"), 0o644)
	if l := e.m.List(Filter{}); len(l) != 1 || l[0].ID != good.ID {
		t.Fatalf("%v", l)
	}
	for _, bad := range []string{"", "../x", "20260101T120000123456Z-0a1b2c3d/..", "nope"} {
		if _, err := e.m.Get(bad); kind(err) != "notfound" {
			t.Errorf("%q: %v", bad, err)
		}
	}
}

func TestListAllCacheFollowsWrites(t *testing.T) {
	e := newEnv(t)
	id := "20260101T120000123456Z-0a1b2c3d"
	dir := sessionDir(e.h, id)
	os.MkdirAll(dir, 0o755)
	meta := filepath.Join(dir, "meta.json")
	write := func(status, note string) {
		os.WriteFile(meta, []byte(`{"id":"`+id+`","command":"x","status":"`+status+`","note":"`+note+`","weird":{"a":[1]}}`), 0o644)
	}
	write("done", "one")
	if got := e.m.List(Filter{}); len(got) != 1 || got[0].Note != "one" || string(got[0].Extra["weird"]) != `{"a":[1]}` {
		t.Fatalf("%+v", got)
	}
	// a write through the manager shows at once
	if _, err := e.m.Update(id, func(r *Record) error { r.Note = "two"; return nil }); err != nil {
		t.Fatal(err)
	}
	if got := e.m.List(Filter{}); got[0].Note != "two" {
		t.Fatal(got[0].Note)
	}
	// a write by another process shows after listFresh
	write("done", "three")
	time.Sleep(listFresh + 50*time.Millisecond)
	if got := e.m.List(Filter{}); got[0].Note != "three" {
		t.Fatal(got[0].Note)
	}
	os.RemoveAll(dir)
	time.Sleep(listFresh + 50*time.Millisecond)
	if got := e.m.List(Filter{}); len(got) != 0 {
		t.Fatal(got)
	}
}
