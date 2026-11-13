package sessions

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/server"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

// slow makes `claude --print` live for a while.
func (e *tenv) slow(sleep string) {
	e.file("ok.jsonl", okStream("sl", 0, 1, 1))
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: "--print", Exec: []string{"sh", "-c", "sleep " + sleep + "; cat " + filepath.Join(e.fb, "ok.jsonl")}})
}

func conflictExtra(err error) map[string]any {
	if e, ok := errs.As(err); ok {
		return e.Extra
	}
	return nil
}

func TestStartGuardsInOrder(t *testing.T) {
	e := newEnv(t)
	e.slow("5")
	ctx := context.Background()
	var order []string
	e.m.d.Guards = []StartGuard{
		func(ctx context.Context, req StartRequest, st Step, slug string, issue int) error {
			order = append(order, "lane")
			if req.Args == "99" {
				return errs.Conflict("dispatch d1 owns acme/app#99", nil)
			}
			return nil
		},
		func(ctx context.Context, req StartRequest, st Step, slug string, issue int) error {
			order = append(order, "blockers")
			if req.Args == "98" && !req.Force {
				return errs.Conflict("#98 is blocked by #1, #2", nil)
			}
			return nil
		},
	}
	a, err := e.m.StartSession(ctx, e.req("implement-issue", "7"))
	mustNoErr(t, err)
	e.status(a.ID, StRunning)

	// 1. live duplicate — always for implement-issue, even without guard
	_, err = e.m.StartSession(ctx, e.req("implement-issue", "7"))
	x := conflictExtra(err)
	if kind(err) != "conflict" || !strings.Contains(err.Error(), "implement-issue already running for acme/app#7 (session "+a.ID+")") ||
		x["id"] != a.ID || x["href"] != "/api/sessions/"+a.ID {
		t.Fatalf("%v %v", err, x)
	}
	// the issue given as a URL is the same issue
	_, err = e.m.StartSession(ctx, e.req("implement-issue", "https://github.com/acme/app/issues/7"))
	if kind(err) != "conflict" {
		t.Fatalf("url form: %v", err)
	}
	// another issue is fine, and the injected guards only run when guard:true
	b, err := e.m.StartSession(ctx, e.req("implement-issue", "8"))
	mustNoErr(t, err)
	if len(order) != 0 {
		t.Fatalf("guards ran without guard:true: %v", order)
	}
	g := e.req("implement-issue", "99")
	g.Guard = true
	if _, err := e.m.StartSession(ctx, g); err == nil || err.Error() != "dispatch d1 owns acme/app#99" {
		t.Fatalf("lane guard: %v", err)
	}
	if strings.Join(order, ",") != "lane" {
		t.Fatalf("order %v", order)
	}
	order = nil
	g = e.req("implement-issue", "98")
	g.Guard = true
	if _, err := e.m.StartSession(ctx, g); err == nil || !strings.Contains(err.Error(), "blocked") {
		t.Fatalf("blocker guard: %v", err)
	}
	g.Force = true
	c, err := e.m.StartSession(ctx, g)
	mustNoErr(t, err)
	// 4. identical start within 30 s
	if _, err := e.m.StartSession(ctx, g); kind(err) != "conflict" {
		t.Fatalf("duplicate window: %v", err)
	}
	r := e.req("refine-issues", "3 4")
	r.Guard = true
	d, err := e.m.StartSession(ctx, r)
	mustNoErr(t, err)
	_, err = e.m.StartSession(ctx, r)
	if kind(err) != "conflict" || !strings.HasPrefix(err.Error(), "just started (session "+d.ID) {
		t.Fatalf("%v", err)
	}
	for _, id := range []string{a.ID, b.ID, c.ID, d.ID} {
		e.m.Stop(ctx, id)
	}
}

func TestStartValidation(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	for _, tc := range []struct {
		name string
		req  StartRequest
		want string
	}{
		{"neither", StartRequest{Repo: "acme/app"}, "invalid"},
		{"both", StartRequest{Step: "implement-issue", Text: "hi", Repo: "acme/app"}, "invalid"},
		{"unknown step", StartRequest{Step: "nope", Repo: "acme/app"}, "invalid"},
		{"dash text", StartRequest{Text: "  --dangerous", Repo: "acme/app"}, "invalid"},
		{"nul text", StartRequest{Text: "a\x00b", Repo: "acme/app"}, "invalid"},
		{"too long", StartRequest{Text: strings.Repeat("x", 32001), Repo: "acme/app"}, "invalid"},
		{"negative issue", StartRequest{Step: "implement-issue", Repo: "acme/app", Issue: -1}, "invalid"},
		{"bad batch", StartRequest{Step: "implement-issue", Args: "1", Repo: "acme/app", Batch: "a b"}, "invalid"},
		{"no repo", StartRequest{Step: "implement-issue", Args: "1"}, "invalid"},
		{"unknown repo", StartRequest{Step: "implement-issue", Args: "1", Repo: "nobody/nothing"}, "invalid"},
		{"unsaved account", StartRequest{Step: "implement-issue", Args: "1", Repo: "acme/app", Account: "ghost"}, "invalid"},
		{"bad model", StartRequest{Step: "implement-issue", Args: "1", Repo: "acme/app", Model: "gpt"}, "invalid"},
		{"no_repo with step", StartRequest{Step: "implement-issue", NoRepo: true}, "invalid"},
		{"bad vault folder", StartRequest{Text: "hi", NoRepo: true, VaultFolder: "../x"}, "invalid"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, err := e.m.StartSession(ctx, tc.req)
			if kind(err) != tc.want {
				t.Fatalf("got %v", err)
			}
		})
	}
	if n := len(e.m.listAll()); n != 0 {
		t.Fatalf("a rejected start left %d records", n)
	}
}

func TestFreeTextStepsRunConcurrently(t *testing.T) {
	e := newEnv(t)
	e.slow("5")
	ctx := context.Background()
	for _, step := range []string{"report-bug", "small-change"} {
		first := e.req(step, "login 500s")
		first.Guard = true
		a, err := e.m.StartSession(ctx, first)
		mustNoErr(t, err)
		e.status(a.ID, StRunning)
		second := e.req(step, "export hangs")
		second.Guard = true
		if _, err := e.m.StartSession(ctx, second); err != nil {
			t.Fatalf("second %s on one repo: %v", step, err)
		}
	}
	// an issue run keeps its duplicate guard
	a, err := e.m.StartSession(ctx, e.req("implement-issue", "7"))
	mustNoErr(t, err)
	e.status(a.ID, StRunning)
	g := e.req("implement-issue", "7")
	g.Guard = true
	if _, err := e.m.StartSession(ctx, g); kind(err) != "conflict" || !strings.Contains(err.Error(), "already running") {
		t.Fatalf("implement-issue duplicate: %v", err)
	}
}

func TestRunsInRouting(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	e.claudeRule("--print", e.file("ok.jsonl", okStream("sr", 0, 1, 1)), 0)
	cwdOf := func(req StartRequest) string {
		t.Helper()
		before := len(e.claudeCalls())
		rec, err := e.m.StartSession(ctx, req)
		mustNoErr(t, err)
		e.status(rec.ID, StDone)
		e.settled(rec.ID)
		calls := e.claudeCalls()
		if len(calls) != before+1 {
			t.Fatalf("calls: %d", len(calls))
		}
		real, _ := filepath.EvalSymlinks(calls[len(calls)-1].Cwd)
		return real
	}
	eval := func(p string) string { r, _ := filepath.EvalSymlinks(p); return r }
	if got := cwdOf(StartRequest{Step: "implement-issue", Args: "1", Repo: "acme/app"}); got != eval(e.repo) {
		t.Errorf("issue: %s", got)
	}
	// GitHub-only steps still start on a repo with a remote
	if got := cwdOf(StartRequest{Step: "after-merge", Args: "3", Repo: "acme/app"}); got != eval(e.repo) {
		t.Errorf("after-merge: %s", got)
	}
	if got := cwdOf(StartRequest{Step: "project-coordinator", Args: "3", Repo: "acme/docs"}); got != eval(e.docs) {
		t.Errorf("project-coordinator: %s", got)
	}
	if got := cwdOf(StartRequest{Step: "create-prd", Repo: "acme/docs"}); got != eval(e.docs) {
		t.Errorf("docs: %s", got)
	}
	if got := cwdOf(StartRequest{Step: "create-prd", Product: "acme/docs"}); got != eval(e.docs) {
		t.Errorf("docs by product: %s", got)
	}
	if got := cwdOf(StartRequest{Step: "release-note"}); got != eval(e.settings.vault) {
		t.Errorf("none -> vault dir: %s", got)
	}
	if got := cwdOf(StartRequest{Text: "a new idea", NoRepo: true, VaultFolder: "05-Work/Acme/Feature"}); got != eval(e.settings.vault) {
		t.Errorf("no_repo: %s", got)
	}
	// an issue URL in the prompt overrides the picked repo when that one is registered
	if got := cwdOf(StartRequest{Text: "look at https://github.com/acme/docs/issues/4", Repo: "acme/app"}); got != eval(e.docs) {
		t.Errorf("url override: %s", got)
	}
	last := e.m.List(Filter{Limit: 1})[0]
	if last.Repo != e.docs || last.CwdPath != e.docs {
		t.Errorf("%+v", last)
	}
	// free-text steps keep the picked repo whatever issue link the pasted text quotes
	for _, step := range []string{"small-change", "report-bug"} {
		if got := cwdOf(StartRequest{Step: step, Args: "seen in https://github.com/acme/docs/issues/4", Repo: "acme/app"}); got != eval(e.repo) {
			t.Errorf("%s ignores the url: %s", step, got)
		}
	}
	// local/ repos cannot run GitHub steps
	e.m.d.Repos.(*fakeRepos).slugs["local/scratch"] = t.TempDir()
	if _, err := e.m.StartSession(ctx, StartRequest{Step: "implement-issue", Args: "1", Repo: "local/scratch"}); kind(err) != "invalid" || !strings.Contains(err.Error(), "has no GitHub remote yet") {
		t.Errorf("local: %v", err)
	}
	if _, err := e.m.StartSession(ctx, StartRequest{Step: "report-bug", Args: "it breaks", Repo: "local/scratch"}); kind(err) != "invalid" || !strings.Contains(err.Error(), "has no GitHub remote yet") {
		t.Errorf("local report-bug: %v", err)
	}
	for _, c := range []struct{ step, args string }{{"small-change", "x"}, {"after-merge", "3"}, {"project-coordinator", "3"}} {
		before := len(e.m.List(Filter{}))
		if _, err := e.m.StartSession(ctx, StartRequest{Step: c.step, Args: c.args, Repo: "local/scratch"}); kind(err) != "invalid" || !strings.Contains(err.Error(), "has no GitHub remote yet") {
			t.Errorf("local %s: %v", c.step, err)
		}
		if n := len(e.m.List(Filter{})); n != before {
			t.Errorf("local %s created a session: %d -> %d", c.step, before, n)
		}
	}
}

func TestRerunReplaysRequest(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	e.claudeRule("--print", e.file("ok.jsonl", okStream("sr", 0, 1, 1)), 0)
	req := e.req("implement-issue", "12")
	req.Model = "opus"
	req.Account = "work"
	a, err := e.m.StartSession(ctx, req)
	mustNoErr(t, err)
	e.status(a.ID, StDone)
	e.settled(a.ID)
	b, err := e.m.Rerun(ctx, a.ID)
	mustNoErr(t, err)
	if b.ID == a.ID || b.Step != "implement-issue" || b.Args != "12" || b.RunModel != "opus" || b.ClaudeCmd != "claude work" {
		t.Fatalf("%+v", b)
	}
	// legacy record without a request: the command is replayed
	id := "20260101T120000123456Z-0a1b2c3d"
	os.MkdirAll(sessionDir(e.h, id), 0o755)
	os.WriteFile(streamPath(e.h, id), nil, 0o644)
	os.WriteFile(metaPath(e.h, id), []byte(`{"id":"`+id+`","command":"/ai-workflow:implement-issue 13","repo":"acme/app","status":"failed","claude_cmd":"claude","started_at":"2026-01-01T00:00:00Z"}`), 0o644)
	c, err := e.m.Rerun(ctx, id)
	mustNoErr(t, err)
	if c.Step != "implement-issue" || c.Args != "13" {
		t.Fatalf("legacy rerun: %+v", c)
	}
	// nothing to rerun
	id2 := "20260101T120000123457Z-0a1b2c3d"
	os.MkdirAll(sessionDir(e.h, id2), 0o755)
	os.WriteFile(metaPath(e.h, id2), []byte(`{"id":"`+id2+`","status":"failed"}`), 0o644)
	if _, err := e.m.Rerun(ctx, id2); kind(err) != "invalid" {
		t.Fatalf("%v", err)
	}
}

func TestResumeStoppedRebindAndGuards(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	e.claudeRule("--resume", e.file("r.jsonl", okStream("sx", 0, 1, 1)), 0)
	e.addRule(fakebin.Rule{Bin: "claude", ArgsContains: "work auth status", Stdout: `{"loggedIn":true}`})
	rec, err := e.m.create(Record{Command: "/blubird:implement-issue 5", Step: "implement-issue", Repo: e.repo, CwdPath: e.repo,
		Status: StStopped, ClaudeCmd: "claude", SessionID: "sx", Link: &Link{"acme", "app", 5}})
	mustNoErr(t, err)
	if _, err := e.m.ResumeStopped(ctx, rec.ID, "ghost"); kind(err) != "invalid" {
		t.Fatalf("unsaved label: %v", err)
	}
	// another live session for the same issue blocks the resume
	other, _ := e.m.create(Record{Command: "/blubird:implement-issue 5", Step: "implement-issue", Repo: e.repo, CwdPath: e.repo,
		Status: StRunning, ClaudeCmd: "claude", Link: &Link{"acme", "app", 5}})
	if _, err := e.m.ResumeStopped(ctx, rec.ID, ""); kind(err) != "conflict" || !strings.Contains(err.Error(), "session "+other.ID+" is already live for this issue") {
		t.Fatalf("%v", err)
	}
	e.m.Update(other.ID, func(r *Record) error { r.Status = StDone; return nil })
	out, err := e.m.ResumeStopped(ctx, rec.ID, "work")
	mustNoErr(t, err)
	if out.ClaudeCmd != "claude work" {
		t.Fatalf("%+v", out)
	}
	e.status(rec.ID, StDone)
	if len(e.claude.transcripts) != 1 || e.claude.transcripts[0] != [4]string{"claude", "claude work", e.repo, "sx"} {
		t.Fatalf("transcript copy: %v", e.claude.transcripts)
	}
	got := e.lastClaude().Args
	if got[len(got)-1] != continuePrompt {
		t.Fatalf("%q", got)
	}
	e.settled(rec.ID)
	if _, err := e.m.ResumeStopped(ctx, rec.ID, ""); kind(err) != "conflict" {
		t.Fatalf("a done session is not resumable: %v", err)
	}
}

func TestStartNowAndStopQueued(t *testing.T) {
	e := newEnv(t)
	ctx := context.Background()
	// long enough that the first three are still running when the fourth is queued, even on a loaded machine
	e.slow("3")
	for i := 0; i < 3; i++ {
		r := e.req("implement-issue", string(rune('1'+i)))
		r.Batch = "q"
		_, err := e.m.StartSession(ctx, r)
		mustNoErr(t, err)
	}
	r := e.req("implement-issue", "4")
	r.Batch = "q"
	q, err := e.m.StartSession(ctx, r)
	mustNoErr(t, err)
	if q.Status != StQueued {
		t.Fatal(q.Status)
	}
	var wg = make(chan error, 2)
	for i := 0; i < 2; i++ {
		go func() { _, err := e.m.StartNow(ctx, q.ID); wg <- err }()
	}
	e1, e2 := <-wg, <-wg
	if (e1 == nil) == (e2 == nil) {
		t.Fatalf("exactly one start-now may win: %v %v", e1, e2)
	}
	e.status(q.ID, StDone)
	// a queued session can be stopped without ever starting
	r2 := e.req("implement-issue", "5")
	r2.Batch = "q2"
	for i := 0; i < 3; i++ {
		x := e.req("implement-issue", string(rune('6'+i)))
		x.Batch = "q2"
		e.m.StartSession(ctx, x)
	}
	q2, _ := e.m.StartSession(ctx, r2)
	out, err := e.m.Stop(ctx, q2.ID)
	mustNoErr(t, err)
	if out.Status != StStopped || out.Note != "" {
		t.Fatalf("%+v", out)
	}
}

func TestTranscriptStream(t *testing.T) {
	e := newEnv(t)
	rec := newBareSession(t, e)
	p := streamPath(e.h, rec.ID)
	l1 := jl(initEv("sx"), textEv("hello"), toolEv("Bash", obj{"command": "ls"}))
	os.WriteFile(p, []byte(l1+`{"type":"assistant","message":{"content":[{"type":"te`), 0o644)
	evs, next, err := e.m.Stream(rec.ID, 0)
	mustNoErr(t, err)
	if len(evs) != 2 || evs[0].Kind != "text" || evs[1].Kind != "tool" || next != int64(len(l1)) {
		t.Fatalf("%d events, next %d (want %d)", len(evs), next, len(l1))
	}
	// the partial tail is withheld while live, parsed once the session is terminal
	evs, next2, _ := e.m.Stream(rec.ID, next)
	if len(evs) != 0 || next2 != next {
		t.Fatalf("partial line served: %v %d", evs, next2)
	}
	f, _ := os.OpenFile(p, os.O_APPEND|os.O_WRONLY, 0o644)
	f.WriteString(`xt","text":"tail"}]}}` + "\n")
	f.Close()
	evs, next3, _ := e.m.Stream(rec.ID, next)
	if len(evs) != 1 || *evs[0].Text != "tail" || next3 <= next {
		t.Fatalf("%v", evs)
	}
	os.WriteFile(p, []byte(l1+`{"type":"assistant","message":{"content":[{"type":"text","text":"unterminated"}]}}`), 0o644)
	e.m.Update(rec.ID, func(r *Record) error { r.Status = StDone; return nil })
	evs, nx, _ := e.m.Stream(rec.ID, int64(len(l1)))
	if len(evs) != 1 || nx == int64(len(l1)) {
		t.Fatalf("terminal tail: %v %d", evs, nx)
	}
	// json shape of the events
	b, _ := json.Marshal(TranscriptEvent{Kind: "result", Cost: nil, IsError: new(bool)})
	if string(b) != `{"cost":null,"is_error":false,"kind":"result","text":null,"tokens":null}` {
		t.Fatalf("%s", b)
	}
	if _, _, err := e.m.Stream(rec.ID, -1); kind(err) != "invalid" {
		t.Fatal(err)
	}
	if _, _, err := e.m.Stream("nope", 0); kind(err) != "notfound" {
		t.Fatal(err)
	}
}

func TestFinalText(t *testing.T) {
	e := newEnv(t)
	rec := newBareSession(t, e)
	os.WriteFile(streamPath(e.h, rec.ID), []byte(jl(textEv("first"), textEv("second"))), 0o644)
	if got := e.m.FinalText(rec.ID); got != "second" {
		t.Fatal(got)
	}
	os.WriteFile(streamPath(e.h, rec.ID), []byte(jl(textEv("first"), resultEv(0, 1, 1, obj{"result": "VERDICT"}), textEv("later"))), 0o644)
	if got := e.m.FinalText(rec.ID); got != "VERDICT" {
		t.Fatal(got)
	}
}

func TestRoutesAndCleanup(t *testing.T) {
	e := newEnv(t)
	e.claudeRule("--print", e.file("ok.jsonl", okStream("sr", 0.5, 1, 1)), 0)
	srv := server.New(server.Config{Port: 8420}, e.bus, Routes(RouteDeps{Manager: e.m}))
	do := func(method, target, body string) (int, map[string]any) {
		var rd *strings.Reader
		if body != "" {
			rd = strings.NewReader(body)
		} else {
			rd = strings.NewReader("")
		}
		r := httptest.NewRequest(method, target, rd)
		r.Host = "127.0.0.1:8420"
		if body != "" {
			r.Header.Set("Content-Type", "application/json")
		}
		w := httptest.NewRecorder()
		srv.Handler().ServeHTTP(w, r)
		var out map[string]any
		json.Unmarshal(w.Body.Bytes(), &out)
		return w.Code, out
	}
	code, out := do("POST", "/api/sessions", `{"step":"implement-issue","args":"3","repo":"acme/app"}`)
	if code != 201 || out["status"] == nil || out["step"] != "implement-issue" || out["skill"] != "blubird:implement-issue" || out["repo"] != "acme/app" {
		t.Fatalf("%d %v", code, out)
	}
	id := out["id"].(string)
	e.status(id, StDone)
	e.settled(id)
	if code, out := do("GET", "/api/sessions/"+id, ""); code != 200 || out["status"] != "done" || out["account"] != "claude" || out["hooks"] != float64(0) {
		t.Fatalf("%d %v", code, out)
	}
	if code, out := do("GET", "/api/sessions?status=done&repo=acme/app&limit=5", ""); code != 200 || len(out["sessions"].([]any)) != 1 ||
		out["stats"].(map[string]any)["month_count"] != float64(1) || out["limits"] == nil {
		t.Fatalf("%d %v", code, out)
	}
	for _, q := range []string{"limit=0", "status=bogus", "before=x", "repo=nope"} {
		if code, out := do("GET", "/api/sessions?"+q, ""); code != 400 || out["error"] == nil {
			t.Errorf("%s: %d %v", q, code, out)
		}
	}
	if code, _ := do("GET", "/api/sessions/20990101T000000000000Z-deadbeef", ""); code != 404 {
		t.Fatal(code)
	}
	if code, _ := do("GET", "/api/sessions/..%2Fx", ""); code != 404 {
		t.Fatal(code)
	}
	if code, out := do("GET", "/api/sessions/"+id+"/stream?offset=0", ""); code != 200 || len(out["events"].([]any)) != 2 || out["offset"].(float64) == 0 {
		t.Fatalf("%d %v", code, out)
	}
	if code, out := do("GET", "/api/sessions/"+id+"/stream?offset=-4", ""); code != 400 || out["error"] != "bad offset" {
		t.Fatalf("%d %v", code, out)
	}
	if code, _ := do("POST", "/api/sessions/"+id+"/stop", ""); code != 409 {
		t.Fatal("stop of a finished session must be 409")
	}
	if code, out := do("POST", "/api/sessions/"+id+"/prompt", `{"text":"-x"}`); code != 400 {
		t.Fatalf("%d %v", code, out)
	}
	if code, out := do("POST", "/api/sessions/"+id+"/answer", `{"round_id":"q-1","answers":{}}`); code != 409 {
		t.Fatalf("%d %v", code, out)
	}
	if code, out := do("POST", "/api/sessions/"+id+"/prompt", `{"text":"go on"}`); code != 200 || out["state"] != "sent" {
		t.Fatalf("%d %v", code, out)
	}
	e.wait(id, func(r Record) bool { return r.Status == StDone && len(e.claudeCalls()) == 2 })
	e.settled(id)
	if code, out := do("POST", "/api/sessions/"+id+"/rerun", ""); code != 201 || out["id"] == id {
		t.Fatalf("%d %v", code, out)
	}
	if code, out := do("POST", "/api/sessions", `{"repo":"acme/app"}`); code != 400 {
		t.Fatalf("%d %v", code, out)
	}
	if code, out := do("POST", "/api/sessions/cleanup", `{}`); code != 400 || out["error"] != "keys must be a list of session keys" {
		t.Fatalf("%d %v", code, out)
	}
	// cleanup removes finished sessions only
	rec2 := newBareSession(t, e) // running: not a target
	e.wait("", func(Record) bool { return true })
	for {
		live := false
		for _, r := range e.m.listAll() {
			if r.ID != rec2.ID && r.Status.Live() {
				live = true
			}
		}
		if !live {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	code, out = do("GET", "/api/sessions/cleanup", "")
	items := out["items"].([]any)
	if code != 200 || len(items) != 2 {
		t.Fatalf("%d %v", code, out)
	}
	keys := []string{rec2.ID}
	for _, it := range items {
		keys = append(keys, it.(map[string]any)["key"].(string))
	}
	kb, _ := json.Marshal(map[string]any{"keys": keys})
	code, out = do("POST", "/api/sessions/cleanup", string(kb))
	if code != 200 || len(out["removed"].([]any)) != 2 {
		t.Fatalf("%d %v", code, out)
	}
	if _, err := os.Stat(sessionDir(e.h, rec2.ID)); err != nil {
		t.Fatal("a live session's directory was removed")
	}
	_ = http.StatusOK
}
