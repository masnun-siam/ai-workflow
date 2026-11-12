package release

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/products"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
	"github.com/masnun-siam/setu/internal/settings"
	"github.com/masnun-siam/setu/internal/testutil/fakebin"
)

type fakeSessions struct {
	mu       sync.Mutex
	n        int
	recs     map[string]sessions.Record
	final    map[string]string
	launched []sessions.Spec
	stopped  []string
}

func (f *fakeSessions) Launch(_ context.Context, s sessions.Spec) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.n++
	if f.recs == nil {
		f.recs, f.final = map[string]sessions.Record{}, map[string]string{}
	}
	id := "s" + string(rune('0'+f.n))
	r := sessions.Record{ID: id, Status: sessions.StRunning, Step: s.Prompt.Step}
	f.recs[id] = r
	f.launched = append(f.launched, s)
	return r, nil
}
func (f *fakeSessions) Get(id string) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r, ok := f.recs[id]
	if !ok {
		return r, errs.NotFound("no session")
	}
	return r, nil
}
func (f *fakeSessions) FinalText(id string) string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.final[id]
}
func (f *fakeSessions) Stop(_ context.Context, id string) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.stopped = append(f.stopped, id)
	return f.recs[id], nil
}
func (f *fakeSessions) finish(id string, st sessions.Status, final string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r := f.recs[id]
	r.Status = st
	f.recs[id] = r
	f.final[id] = final
}
func (f *fakeSessions) count(step string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	n := 0
	for _, s := range f.launched {
		if s.Prompt.Step == step {
			n++
		}
	}
	return n
}

type fakePrompts struct{}

func (fakePrompts) BuildIn(step, args, repo string) (prompts.Prompt, error) {
	return prompts.Prompt{Step: step, Display: "/" + step + " " + args, Text: step + " ARGUMENTS: " + args}, nil
}

type fakeGrind struct {
	mu      sync.Mutex
	state   string
	started int
}

func (g *fakeGrind) Get(repo string, pr int) (GrindStatus, bool) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.state == "" {
		return GrindStatus{}, false
	}
	return GrindStatus{Repo: repo, PR: pr, State: g.state}, true
}
func (g *fakeGrind) StartGrind(_ context.Context, repo string, pr int, by string) (sessions.Record, error) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.started++
	g.state = "running"
	return sessions.Record{ID: "g1"}, nil
}

type fakeSettings struct{ s settings.Settings }

func (f fakeSettings) Get() settings.Settings { return f.s }

type fakeProducts struct{}

func (fakeProducts) Products() []products.Product {
	return []products.Product{{DocsRepo: "acme/docs", Repos: []products.ProductRepo{
		{Name: "docs", Role: "docs", Repo: "acme/docs"}, {Name: "app", Role: "backend", Repo: "acme/app"}}}}
}
func (fakeProducts) Repos() []products.Repo {
	return []products.Repo{{Slug: "acme/app"}, {Slug: "acme/docs"}}
}

type fakeNotify struct {
	mu sync.Mutex
	n  []notify.Note
}

func (f *fakeNotify) Notify(ev string, n notify.Note) {
	f.mu.Lock()
	f.n = append(f.n, n)
	f.mu.Unlock()
}

type env struct {
	t    *testing.T
	s    *Service
	ss   *fakeSessions
	gr   *fakeGrind
	nt   *fakeNotify
	bins string
	now  time.Time
	mu   sync.Mutex
}

func newEnv(t *testing.T, rules []fakebin.Rule) *env {
	root := t.TempDir()
	t.Setenv("HOME", root)
	t.Setenv("SETU_HOME", filepath.Join(root, "setu"))
	h := &home.Home{Root: filepath.Join(root, "setu")}
	_ = os.MkdirAll(h.Root, 0o700)
	bins := filepath.Join(root, "bin")
	fakebin.Install(t, bins)
	fakebin.WriteRules(t, bins, rules)
	e := &env{t: t, ss: &fakeSessions{}, gr: &fakeGrind{}, nt: &fakeNotify{}, bins: bins, now: time.Date(2026, 11, 12, 9, 0, 0, 0, time.UTC)}
	st := settings.Settings{ReleaseNote: settings.ReleaseNote{ChannelName: "dc-supports", ChannelID: "C06RSFFRUFM"},
		Repos: map[string]settings.RepoSettings{}}
	e.s = New(Deps{Home: h, Sessions: e.ss, Prompts: fakePrompts{}, GH: gh.New(), Grind: e.gr,
		Settings: fakeSettings{st}, Products: fakeProducts{}, Notify: e.nt,
		Now: func() time.Time { e.mu.Lock(); defer e.mu.Unlock(); return e.now }})
	return e
}

func (e *env) advance(d time.Duration) { e.mu.Lock(); e.now = e.now.Add(d); e.mu.Unlock() }

func (e *env) must(r Release, err error) Release {
	e.t.Helper()
	if err != nil {
		e.t.Fatal(err)
	}
	return r
}

func (e *env) stage(id string) string {
	e.t.Helper()
	r, err := e.s.Get(id)
	if err != nil {
		e.t.Fatal(err)
	}
	return r.Stage
}

func slackCalls(t *testing.T, dir string) []fakebin.Call {
	var out []fakebin.Call
	for _, c := range fakebin.Calls(t, dir) {
		if c.Bin == "slackcli" {
			out = append(out, c)
		}
	}
	return out
}

const prURL = "https://github.com/acme/app/pull/77"

// toNotify drives a release to the notify stage and returns its id.
func toNotify(e *env) string {
	r := e.must(e.s.Cut(context.Background(), "acme/app", false))
	e.ss.finish(*r.CutSession, sessions.StDone, "done\nSETU-RELEASE: {\"pr\":\""+prURL+"\",\"thread\":null}")
	e.s.tick(context.Background(), true)
	e.gr.state = "approved"
	e.s.tick(context.Background(), true)
	e.s.tick(context.Background(), true)
	return r.ID
}

var merged = fakebin.Rule{Bin: "gh", ArgsContains: "pr view 77", Stdout: `{"state":"MERGED","mergedAt":"2026-11-12T08:00:00Z"}`}
var slackOK = fakebin.Rule{Bin: "slackcli", ArgsPrefix: []string{"messages", "send"}, Stdout: `{"ok":true,"message":{"permalink":"https://x.slack.com/archives/C06RSFFRUFM/p1"}}`}

func TestParseResult(t *testing.T) {
	tests := []struct {
		name, in string
		ok       bool
		pr       string
		dry      string
		reason   string
	}{
		{"pr", "text\nSETU-RELEASE: {\"pr\":\"" + prURL + "\",\"thread\":\"https://t\"}\n", true, prURL, "", ""},
		{"null pr with reason", `SETU-RELEASE: {"pr":null,"reason":"behind 3"}`, true, "", "", "behind 3"},
		{"dry run", `x` + "\n" + `SETU-RELEASE: {"pr":null,"thread":null,"dry_run":"/tmp/d"}`, true, "", "/tmp/d", ""},
		{"last line wins", "SETU-RELEASE: {\"pr\":\"a\"}\nSETU-RELEASE: {\"pr\":\"" + prURL + "\"}", true, prURL, "", ""},
		{"backticked", "`SETU-RELEASE: {\"pr\":\"" + prURL + "\"}`", true, prURL, "", ""},
		{"none", "all done", false, "", "", ""},
		{"bad json", "SETU-RELEASE: {nope", false, "", "", ""},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			r, ok := ParseResult(tc.in)
			if ok != tc.ok {
				t.Fatalf("ok = %v", ok)
			}
			if !ok {
				return
			}
			got := ""
			if r.PR != nil {
				got = *r.PR
			}
			if got != tc.pr || r.DryRun != tc.dry || r.Reason != tc.reason {
				t.Fatalf("got %+v", r)
			}
		})
	}
	if n, ok := PRNumber(prURL); !ok || n != 77 {
		t.Fatal("PRNumber")
	}
	if _, ok := PRNumber("https://github.com/a/b/issues/3"); ok {
		t.Fatal("issue url")
	}
}

func TestFlowEndToEnd(t *testing.T) {
	e := newEnv(t, []fakebin.Rule{merged, slackOK})
	ctx := context.Background()
	r := e.must(e.s.Cut(ctx, "acme/app", false))
	if r.Stage != StCut || r.Head != "staging" || r.Base != "master" || r.CutSession == nil {
		t.Fatalf("cut: %+v", r)
	}
	if got := e.ss.launched[0]; got.Prompt.Step != "release-pr" || got.Args != "staging master" || got.Cwd != "acme/app" || got.Kind != "release" {
		t.Fatalf("launch: %+v", got)
	}
	// running session: nothing moves
	e.s.tick(ctx, true)
	if e.stage(r.ID) != StCut {
		t.Fatal("moved early")
	}
	e.ss.finish(*r.CutSession, sessions.StDone, "SETU-RELEASE: {\"pr\":\""+prURL+"\",\"thread\":\"https://slack/t\"}")
	e.s.tick(ctx, true)
	g := e.must(e.s.Get(r.ID))
	if g.Stage != StGrind || *g.PR != 77 || *g.Thread != "https://slack/t" {
		t.Fatalf("grind: %+v", g)
	}
	// manual grind start is idempotent while running
	e.must(e.s.Grind(ctx, r.ID))
	e.must(e.s.Grind(ctx, r.ID))
	if e.gr.started != 1 {
		t.Fatalf("grind started %d times", e.gr.started)
	}
	// approved -> merge. The PR is not merged yet in this phase of the test: use a closed rule order.
	fakebin.WriteRules(t, e.bins, []fakebin.Rule{{Bin: "gh", ArgsContains: "pr view 77", Stdout: `{"state":"OPEN","mergedAt":null}`}, slackOK})
	e.gr.state = "approved"
	e.s.tick(ctx, true)
	if e.stage(r.ID) != StMerge {
		t.Fatalf("stage %s", e.stage(r.ID))
	}
	// merged on GitHub -> notify, draft started exactly once however many ticks follow
	fakebin.WriteRules(t, e.bins, []fakebin.Rule{merged, slackOK})
	e.s.tick(ctx, true)
	e.s.tick(ctx, true)
	n := e.must(e.s.Get(r.ID))
	if n.Stage != StNotify || n.MergedAt == nil || *n.MergedAt != "2026-11-12T08:00:00Z" || n.NoteSession == nil {
		t.Fatalf("notify: %+v", n)
	}
	if e.ss.count("release-note") != 1 {
		t.Fatalf("drafts: %d", e.ss.count("release-note"))
	}
	var draft sessions.Spec
	for _, s := range e.ss.launched {
		if s.Prompt.Step == "release-note" {
			draft = s
		}
	}
	file := filepath.Join(e.s.dir(), r.ID, "note.md")
	if draft.Args != prURL+" --draft "+file {
		t.Fatalf("draft args %q", draft.Args)
	}
	if len(e.nt.n) == 0 {
		t.Fatal("no release notification")
	}
	// the draft is written, the session ends
	if err := os.WriteFile(file, []byte("<!here>\n*Release Note*"), 0o644); err != nil {
		t.Fatal(err)
	}
	e.ss.finish(*n.NoteSession, sessions.StDone, "ok")
	e.s.tick(ctx, true)
	e.s.tick(ctx, true)
	v := e.must(e.s.Get(r.ID))
	if v.Note == nil || !strings.HasPrefix(*v.Note, "<!here>") {
		t.Fatalf("note: %+v", v.Note)
	}
	// edit
	v = e.must(e.s.SaveNote(r.ID, "<!here>\n*Release Note - edited*"))
	if !strings.Contains(*v.Note, "edited") {
		t.Fatal("not saved")
	}
	if _, err := e.s.SaveNote(r.ID, strings.Repeat("x", MaxNote+1)); errs.KindOf(err) != errs.KInvalid {
		t.Fatalf("long note: %v", err)
	}
	// two concurrent posts: exactly one send
	var wg sync.WaitGroup
	var okN, conflict int
	var cm sync.Mutex
	for i := 0; i < 2; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := e.s.Post(ctx, r.ID)
			cm.Lock()
			defer cm.Unlock()
			switch {
			case err == nil:
				okN++
			case errs.KindOf(err) == errs.KConflict:
				conflict++
			default:
				t.Errorf("post: %v", err)
			}
		}()
	}
	wg.Wait()
	if okN != 1 || conflict != 1 {
		t.Fatalf("ok %d conflict %d", okN, conflict)
	}
	calls := slackCalls(t, e.bins)
	if len(calls) != 1 {
		t.Fatalf("slackcli called %d times", len(calls))
	}
	want := []string{"messages", "send", "--recipient-id", "C06RSFFRUFM", "--message-file", file, "--json"}
	if strings.Join(calls[0].Args, " ") != strings.Join(want, " ") {
		t.Fatalf("args %v", calls[0].Args)
	}
	d := e.must(e.s.Get(r.ID))
	if d.Stage != StDone || d.NotePostedAt == nil || d.NotePermalink == nil || !strings.Contains(*d.NotePermalink, "slack.com") {
		t.Fatalf("done: %+v", d)
	}
	if _, err := e.s.Post(ctx, r.ID); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("repost: %v", err)
	}
	if len(slackCalls(t, e.bins)) != 1 {
		t.Fatal("reposted")
	}
}

func TestPostFailureIsNeverRetried(t *testing.T) {
	e := newEnv(t, []fakebin.Rule{merged, {Bin: "slackcli", Stderr: "channel_not_found", Exit: 1}})
	id := toNotify(e)
	if e.stage(id) != StNotify {
		t.Fatalf("stage %s", e.stage(id))
	}
	if _, err := e.s.Post(context.Background(), id); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("no note yet: %v", err) // draft session is live and there is no file
	}
	file := filepath.Join(e.s.dir(), id, "note.md")
	r, _ := e.s.load(id)
	e.ss.finish(*r.NoteSess, sessions.StDone, "ok")
	_ = os.WriteFile(file, []byte("note"), 0o644)
	_, err := e.s.Post(context.Background(), id)
	if errs.KindOf(err) != errs.KUpstream || !strings.Contains(err.Error(), "channel_not_found") {
		t.Fatalf("post: %v", err)
	}
	v := e.must(e.s.Get(id))
	if v.Stage != StNotify || v.Error == nil || v.NotePostedAt != nil {
		t.Fatalf("after failure: %+v", v)
	}
	if _, err := e.s.Post(context.Background(), id); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("repost: %v", err)
	}
	if _, err := e.s.SaveNote(id, "again"); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("edit after attempt: %v", err)
	}
	if n := len(slackCalls(t, e.bins)); n != 1 {
		t.Fatalf("slackcli called %d times", n)
	}
}

func TestDryRunAndFailures(t *testing.T) {
	e := newEnv(t, nil)
	ctx := context.Background()
	r := e.must(e.s.Cut(ctx, "acme/app", true))
	if !r.DryRun || e.ss.launched[0].Args != "--dry-run staging master" {
		t.Fatalf("dry: %+v / %q", r, e.ss.launched[0].Args)
	}
	e.ss.finish(*r.CutSession, sessions.StDone, `SETU-RELEASE: {"pr":null,"thread":null,"dry_run":"/h/release-pr/acme-app-2026-11-12"}`)
	e.s.tick(ctx, true)
	v := e.must(e.s.Get(r.ID))
	if v.Stage != StDryRun || *v.DryRunDir != "/h/release-pr/acme-app-2026-11-12" {
		t.Fatalf("%+v", v)
	}
	// a dry run frees the repo
	r2 := e.must(e.s.Cut(ctx, "acme/app", false))
	e.ss.finish(*r2.CutSession, sessions.StDone, "I stopped.")
	e.s.tick(ctx, true)
	if v := e.must(e.s.Get(r2.ID)); v.Stage != StFailed || !strings.Contains(*v.Error, "SETU-RELEASE") {
		t.Fatalf("%+v", v)
	}
	r3 := e.must(e.s.Cut(ctx, "acme/app", false))
	e.ss.finish(*r3.CutSession, sessions.StDone, `SETU-RELEASE: {"pr":null,"reason":"behind 4 commits"}`)
	e.s.tick(ctx, true)
	if v := e.must(e.s.Get(r3.ID)); v.Stage != StFailed || *v.Error != "behind 4 commits" {
		t.Fatalf("%+v", v)
	}
	r4 := e.must(e.s.Cut(ctx, "acme/app", false))
	e.ss.finish(*r4.CutSession, sessions.StFailed, "")
	e.s.tick(ctx, true)
	if v := e.must(e.s.Get(r4.ID)); v.Stage != StFailed {
		t.Fatalf("%+v", v)
	}
}

func TestOneOpenReleasePerRepoAndSkip(t *testing.T) {
	e := newEnv(t, nil)
	ctx := context.Background()
	r := e.must(e.s.Cut(ctx, "acme/app", false))
	_, err := e.s.Cut(ctx, "ACME/app", false)
	ae, ok := errs.As(err)
	if errs.KindOf(err) != errs.KConflict || !ok || ae.Extra["id"] != r.ID {
		t.Fatalf("second cut: %v", err)
	}
	if _, err := e.s.Cut(ctx, "acme/other", false); errs.KindOf(err) != errs.KNotFound {
		t.Fatalf("unknown repo: %v", err)
	}
	if _, err := e.s.Cut(ctx, "nope", false); errs.KindOf(err) != errs.KInvalid {
		t.Fatalf("bad slug: %v", err)
	}
	s := e.must(e.s.Skip(r.ID))
	if s.Stage != StSkipped || len(e.ss.stopped) != 1 {
		t.Fatalf("skip: %+v %v", s, e.ss.stopped)
	}
	if _, err := e.s.Skip(r.ID); errs.KindOf(err) != errs.KConflict {
		t.Fatalf("reskip: %v", err)
	}
	e.must(e.s.Cut(ctx, "acme/app", false)) // free again
}

func TestPartialAndBranchOptions(t *testing.T) {
	e := newEnv(t, nil)
	_, err := e.s.CutWith(context.Background(), "acme/app", CutOpts{Partial: true, Head: "develop", Base: "main"})
	if err != nil {
		t.Fatal(err)
	}
	l := e.ss.launched[0]
	if l.Args != "develop main" || len(l.Instructions) != 1 || !strings.Contains(l.Instructions[0], "partial release") {
		t.Fatalf("%+v", l)
	}
	if _, err := e.s.CutWith(context.Background(), "acme/app", CutOpts{Head: "--evil"}); errs.KindOf(err) != errs.KInvalid {
		t.Fatalf("head: %v", err)
	}
}

func TestReposAheadAndLastRelease(t *testing.T) {
	e := newEnv(t, []fakebin.Rule{{Bin: "gh", ArgsContains: "compare/master...staging", Stdout: "7\n"}})
	// a finished release
	r := e.must(e.s.Cut(context.Background(), "acme/app", false))
	_, _ = e.s.mutate(r.ID, func(x *record) error {
		n := 70
		x.Stage, x.PR, x.MergedAt = StDone, &n, sp("2026-11-01T00:00:00Z")
		return nil
	})
	rows := e.s.Repos("acme/docs")
	if len(rows) != 1 || rows[0].Repo != "acme/app" || rows[0].Ahead == nil || *rows[0].Ahead != 7 {
		t.Fatalf("%+v", rows)
	}
	if rows[0].LastRelease == nil || rows[0].LastRelease.PR != 70 || rows[0].Open != nil {
		t.Fatalf("%+v", rows[0])
	}
	if len(rows[0].Actions) != 3 || rows[0].Actions[0].Path != "/api/releases" {
		t.Fatalf("%+v", rows[0].Actions)
	}
	if got := e.s.Repos("nobody/docs"); len(got) != 0 {
		t.Fatalf("%+v", got)
	}
}

func TestMergedHintAndClosedPR(t *testing.T) {
	e := newEnv(t, []fakebin.Rule{{Bin: "gh", ArgsContains: "pr view 77", Stdout: `{"state":"CLOSED","mergedAt":null}`}})
	ctx := context.Background()
	r := e.must(e.s.Cut(ctx, "acme/app", false))
	e.ss.finish(*r.CutSession, sessions.StDone, `SETU-RELEASE: {"pr":"`+prURL+`","thread":null}`)
	e.s.tick(ctx, true)
	// throttled: a second non-forced tick right away asks gh only once
	e.s.tick(ctx, false)
	if v := e.must(e.s.Get(r.ID)); v.Stage != StFailed || !strings.Contains(*v.Error, "closed") {
		t.Fatalf("%+v", v)
	}
	// poller hint
	e2 := newEnv(t, nil)
	e2.s.d.Merged = func(repo string, n int) (string, bool) { return "2026-11-12T07:00:00Z", repo == "acme/app" && n == 77 }
	r = e2.must(e2.s.Cut(ctx, "acme/app", false))
	e2.ss.finish(*r.CutSession, sessions.StDone, `SETU-RELEASE: {"pr":"`+prURL+`"}`)
	e2.s.tick(ctx, false)
	e2.s.tick(ctx, false)
	if v := e2.must(e2.s.Get(r.ID)); v.Stage != StNotify || *v.MergedAt != "2026-11-12T07:00:00Z" {
		t.Fatalf("%+v", v)
	}
}

func TestRoutes(t *testing.T) {
	e := newEnv(t, []fakebin.Rule{{Bin: "gh", ArgsContains: "compare", Stdout: "2"}})
	mux := http.NewServeMux()
	for _, r := range Routes(e.s) {
		mux.Handle(r.Pattern, r.Handler)
	}
	do := func(method, path, body string) (int, map[string]any) {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		if body != "" {
			req.Header.Set("Content-Type", "application/json")
		}
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, req)
		var m map[string]any
		_ = json.Unmarshal(w.Body.Bytes(), &m)
		return w.Code, m
	}
	code, m := do("POST", "/api/releases", `{"repo":"acme/app","dry_run":true}`)
	if code != 201 || m["stage"] != "cut" || m["dry_run"] != true {
		t.Fatalf("%d %v", code, m)
	}
	id := m["id"].(string)
	if code, m = do("POST", "/api/releases", `{"repo":"acme/app"}`); code != 409 || m["id"] != id {
		t.Fatalf("%d %v", code, m)
	}
	if code, _ = do("POST", "/api/releases/bad-id/skip", ""); code != 404 {
		t.Fatalf("bad id: %d", code)
	}
	if code, m = do("GET", "/api/releases?product=acme/docs", ""); code != 200 || len(m["releases"].([]any)) != 1 || len(m["repos"].([]any)) != 1 {
		t.Fatalf("%d %v", code, m)
	}
	if code, _ = do("PUT", "/api/releases/"+id+"/note", `{"text":"hi"}`); code != 409 {
		t.Fatalf("note in cut: %d", code)
	}
	if code, m = do("POST", "/api/releases/"+id+"/skip", ""); code != 200 || m["stage"] != "skipped" {
		t.Fatalf("%d %v", code, m)
	}
	if code, _ = do("POST", "/api/releases/"+id+"/post", ""); code != 409 {
		t.Fatalf("post skipped: %d", code)
	}
}
