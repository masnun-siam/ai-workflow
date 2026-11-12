package grind

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
	"github.com/masnun-siam/setu/internal/settings"
)

type fakeSessions struct {
	mu       sync.Mutex
	recs     []sessions.Record
	started  []sessions.StartRequest
	launched []sessions.Spec
	prompts  [][2]string
	n        int
}

func (f *fakeSessions) add(r sessions.Record) { f.recs = append([]sessions.Record{r}, f.recs...) }

func (f *fakeSessions) StartSession(_ context.Context, req sessions.StartRequest) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.started = append(f.started, req)
	f.n++
	m := reURLRepo.FindStringSubmatch(req.Args)
	r := sessions.Record{ID: "start" + itoa(f.n), Step: "pr-grind", Args: req.Args, Status: sessions.StRunning, StartedAt: stamp(t0)}
	if m != nil {
		r.Link = &sessions.Link{Owner: m[1], Repo: m[2], Issue: atoi(m[3])}
	}
	f.add(r)
	return r, nil
}

func (f *fakeSessions) Launch(_ context.Context, s sessions.Spec) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.launched = append(f.launched, s)
	f.n++
	r := sessions.Record{ID: "launch" + itoa(f.n), Step: s.Prompt.Step, Command: s.Prompt.Display, Link: s.Link, CwdPath: s.Cwd,
		Status: sessions.StRunning, ClaudeCmd: s.Cmd, StartedAt: stamp(t0)}
	f.add(r)
	return r, nil
}

func (f *fakeSessions) List(fl sessions.Filter) []sessions.Record {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []sessions.Record
	for _, r := range f.recs {
		if fl.Step != "" && r.Step != fl.Step {
			continue
		}
		if fl.Repo != "" && (r.Link == nil || !strings.EqualFold(r.Link.Owner+"/"+r.Link.Repo, fl.Repo)) {
			continue
		}
		out = append(out, r)
	}
	return out
}

func (f *fakeSessions) SendPrompt(_ context.Context, id, text string, _ int) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.prompts = append(f.prompts, [2]string{id, text})
	return "sent", nil
}

func (f *fakeSessions) Public(r sessions.Record) sessions.Session { return sessions.Session{ID: r.ID} }

type fakePrompts struct{}

func (fakePrompts) BuildIn(step, args, repo string) (prompts.Prompt, error) {
	return prompts.Prompt{Step: step, Display: "/" + step + " " + args, Text: "BODY ARGUMENTS: " + args}, nil
}

type fakeNotify struct {
	mu   sync.Mutex
	got  []string
	note []notify.Note
}

func (f *fakeNotify) Notify(ev string, n notify.Note) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.got = append(f.got, ev+" "+n.ID)
	f.note = append(f.note, n)
}

type fakeLanes struct{ owned map[int]bool }

func (f fakeLanes) ActiveLane(_ string, _ int, pr int) (string, bool) {
	if f.owned[pr] {
		return "abc123abc123", true
	}
	return "", false
}
func (f fakeLanes) GrindMode(string) (string, bool) { return "", false }

type fakeSnaps struct{ snap poller.Snapshot }

func (f fakeSnaps) Snapshot(string) poller.Snapshot { return f.snap }

type fakeRepos struct{ path string }

func (f fakeRepos) Resolve(context.Context, string) (string, string, error) {
	if f.path == "" {
		return "", "", os.ErrNotExist
	}
	return f.path, "acme/app", nil
}

type srv struct {
	*env
	svc  *Service
	ses  *fakeSessions
	note *fakeNotify
}

func newSrv(t *testing.T, mut func(*Deps)) *srv {
	t.Helper()
	e := newEnv(t)
	e.writeJSON("ui_settings.json", map[string]any{
		"reviewers":        []any{map[string]string{"id": "r1", "name": "Bob", "slack_id": "UBOB000001", "github_login": "bob"}},
		"active_reviewers": []string{"r1"},
		"slack_channels":   []any{map[string]string{"id": "C0AAAAAAAA", "name": "reviews"}},
		"repos":            map[string]any{"acme/app": map[string]any{"auto_grind": true}},
	})
	s := &srv{env: e, ses: &fakeSessions{}, note: &fakeNotify{}}
	d := Deps{Home: e.h, GH: e.gh, Sessions: s.ses, Prompts: fakePrompts{}, Settings: settings.Open(e.h, nil),
		Notify: s.note, Products: fakeRepos{path: "/work/app"}, Now: func() time.Time { return e.now }}
	if mut != nil {
		mut(&d)
	}
	s.svc = New(d)
	return s
}

func (s *srv) statusOf(pr int) Status {
	s.t.Helper()
	st, ok := s.svc.Get("acme/app", pr)
	if !ok {
		s.t.Fatalf("no grind for %d", pr)
	}
	return st
}

func TestIndexStates(t *testing.T) {
	s := newSrv(t, nil)
	s.seedState("next-poll: 2026-11-12T11:00:00Z")
	if st := s.statusOf(7); st.State != StIdle || st.Rounds != 0 {
		t.Fatalf("active file without a session: %+v", st)
	}
	s.ses.add(sessions.Record{ID: "s1", Step: "pr-grind", Status: sessions.StRunning, StartedAt: stamp(t0), Link: &sessions.Link{Owner: "acme", Repo: "app", Issue: 7}})
	st := s.statusOf(7)
	if st.State != StRunning || st.Session == nil || *st.Session != "s1" {
		t.Fatalf("live session: %+v", st)
	}
	// paused wins over a live session; done with an older live session stays done
	if err := s.files().Update(Key{"acme", "app", 7}, t0, func(d *Doc) error { d.Set("paused", "2026-11-12T10:00:00Z - CI red"); return nil }); err != nil {
		t.Fatal(err)
	}
	if st := s.statusOf(7); st.State != StPaused || *st.Reason != "CI red" {
		t.Fatalf("paused: %+v", st)
	}
	s.ses.recs[0].Status = sessions.StDone
	_ = s.files().Update(Key{"acme", "app", 7}, t0, func(d *Doc) error {
		d.Del("paused")
		d.Set("done", "2026-11-12T10:30:00Z - approved by bob")
		return nil
	})
	if st := s.statusOf(7); st.State != StApproved || *st.Reason != "approved by bob" || st.Session == nil || *st.Session != "s1" {
		t.Fatalf("approved: %+v", st)
	}
	// a session that started after the done stamp is a restart
	s.ses.add(sessions.Record{ID: "s2", Step: "pr-grind", Status: sessions.StStarting, StartedAt: "2026-11-12T10:45:00Z", Link: &sessions.Link{Owner: "acme", Repo: "app", Issue: 7}})
	if st := s.statusOf(7); st.State != StRunning {
		t.Fatalf("restart: %+v", st)
	}
	// a live session with no file is running, round 0
	s.ses.add(sessions.Record{ID: "s3", Step: "pr-grind", Status: sessions.StRunning, StartedAt: stamp(t0), Args: "https://github.com/acme/app/pull/9", Link: &sessions.Link{Owner: "acme", Repo: "app", Issue: 9}})
	st9 := s.statusOf(9)
	if st9.State != StRunning || st9.Rounds != 0 || st9.Thread != nil {
		t.Fatalf("no file: %+v", st9)
	}
	if _, ok := s.svc.Get("acme/app", 99); ok {
		t.Fatal("unknown grind found")
	}
	if n := len(s.svc.Index()); n != 2 {
		t.Fatalf("index has %d", n)
	}
}

func TestIndexGithubThread(t *testing.T) {
	s := newSrv(t, nil)
	s.seedState()
	b, _ := os.ReadFile(s.h.Path("pr-grind", "acme-app-7.md"))
	text := strings.Replace(string(b), "thread: https://acme.slack.com/archives/C0AAAAAAAA/p1789128876624469", "thread: github", 1)
	_ = os.WriteFile(s.h.Path("pr-grind", "acme-app-7.md"), []byte(text), 0o600)
	if st := s.statusOf(7); st.State != StIdle || st.Thread != nil {
		t.Fatalf("%+v", st)
	}
}

func TestTickDecisions(t *testing.T) {
	due := "next-poll: 2026-11-12T09:59:00Z"
	later := "next-poll: 2026-11-12T10:30:00Z"
	key := "acme/app#7"
	t.Run("due starts a re-entry", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState(due, "reviewer: bob")
		s.ses.add(sessions.Record{ID: "old", Step: "pr-grind", Status: sessions.StDone, CwdPath: "/work/app-old", ClaudeCmd: "cc-work",
			Link: &sessions.Link{Owner: "acme", Repo: "app", Issue: 7}})
		if got := s.svc.Tick(context.Background())[key]; got != OutStarted {
			t.Fatalf("outcome %s", got)
		}
		if len(s.ses.launched) != 1 {
			t.Fatal("no launch")
		}
		sp := s.ses.launched[0]
		if sp.Cwd != "/work/app-old" || sp.Cmd != "cc-work" || !sp.Gate || sp.Kind != "grind" {
			t.Fatalf("spec %+v", sp)
		}
		if sp.Args != "https://acme.slack.com/archives/C0AAAAAAAA/p1789128876624469" || sp.Link.Issue != 7 {
			t.Fatalf("args/link %+v %+v", sp.Args, sp.Link)
		}
		if len(sp.Instructions) != 1 || sp.Instructions[0] != prompts.Reentry || len(sp.ExtraFiles) != 1 {
			t.Fatalf("instructions/fds %+v", sp)
		}
		if strings.Join(sp.Env, " ") != "SETU_HEADLESS=1 AIW_HEADLESS=1" {
			t.Fatalf("env %v", sp.Env)
		}
		d, _ := s.files().Read(Key{"acme", "app", 7})
		if d.Get("next-poll") != "2026-11-12T10:25:00Z" || d.Get("ci-seen") == "" {
			t.Fatalf("header %q %q", d.Get("next-poll"), d.Get("ci-seen"))
		}
		// the live session now makes the next tick busy
		if got := s.svc.Tick(context.Background())[key]; got != OutBusy {
			t.Fatalf("second tick %s", got)
		}
	})
	t.Run("github thread uses the PR url", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState(due)
		b, _ := os.ReadFile(s.h.Path("pr-grind", "acme-app-7.md"))
		_ = os.WriteFile(s.h.Path("pr-grind", "acme-app-7.md"), []byte(strings.Replace(string(b), "thread: https://acme.slack.com/archives/C0AAAAAAAA/p1789128876624469", "thread: github", 1)), 0o600)
		s.svc.Tick(context.Background())
		if len(s.ses.launched) != 1 || s.ses.launched[0].Args != testPR {
			t.Fatalf("%+v", s.ses.launched)
		}
		if s.ses.launched[0].Cwd != "/work/app" { // from products.Resolve
			t.Fatalf("cwd %s", s.ses.launched[0].Cwd)
		}
	})
	t.Run("skips", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState(due, "paused: 2026-11-12T09:00:00Z - waiting")
		if got := s.svc.Tick(context.Background()); len(got) != 0 {
			t.Fatalf("paused ticked: %v", got)
		}
		s = newSrv(t, nil)
		s.seedState("done: 2026-11-12T09:00:00Z - approved", due)
		if got := s.svc.Tick(context.Background()); len(got) != 0 {
			t.Fatalf("done ticked: %v", got)
		}
		s = newSrv(t, nil)
		s.seedState() // no next-poll
		if got := s.svc.Tick(context.Background()); len(got) != 0 {
			t.Fatalf("no next-poll ticked: %v", got)
		}
	})
	t.Run("locked", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState(due)
		f, ok, err := home.TryLock(s.h.Path("pr-grind", "acme-app-7"))
		if err != nil || !ok {
			t.Fatal(err, ok)
		}
		defer f.Close()
		if got := s.svc.Tick(context.Background())[key]; got != OutLocked {
			t.Fatalf("%s", got)
		}
	})
	t.Run("merged writes done", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState(due)
		s.w.State = "MERGED"
		if got := s.svc.Tick(context.Background())[key]; got != OutClosed {
			t.Fatalf("%s", got)
		}
		d, _ := s.files().Read(Key{"acme", "app", 7})
		if !strings.HasSuffix(d.Get("done"), " - merged") {
			t.Fatalf("done %q", d.Get("done"))
		}
		if len(s.ses.launched) != 0 {
			t.Fatal("started on a merged PR")
		}
	})
	t.Run("gh error", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState(due)
		s.w.State = ""
		s.w.mu.Lock()
		s.w.mu.Unlock()
		s.gh.Reset()
		if got := s.svc.Tick(context.Background())[key]; got != OutError {
			t.Fatalf("%s", got)
		}
	})
	t.Run("not due and quiet", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState(later, "reviewer: bob", "poll-since: 2026-11-12T09:30:00Z", "ci-seen: "+testHead+" green")
		s.w.Reviews = arr(review(1, "bob", "COMMENTED", "2026-11-12T09:00:00Z", testHead, "old"),
			review(2, "carol", "COMMENTED", "2026-11-12T09:50:00Z", testHead, "not a reviewer"))
		if got := s.svc.Tick(context.Background())[key]; got != OutIdle {
			t.Fatalf("%s", got)
		}
	})
	t.Run("new review triggers and moves poll-since", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState(later, "reviewer: bob", "reviewers: bob", "poll-since: 2026-11-12T09:30:00Z", "ci-seen: "+testHead+" green")
		s.w.Reviews = arr(review(1, "bob", "COMMENTED", "2026-11-12T09:45:00Z", testHead, "new"))
		if got := s.svc.Tick(context.Background())[key]; got != OutStarted {
			t.Fatalf("%s", got)
		}
		d, _ := s.files().Read(Key{"acme", "app", 7})
		if d.Get("poll-since") != "2026-11-12T09:45:00Z" {
			t.Fatalf("poll-since %q", d.Get("poll-since"))
		}
	})
	t.Run("unresolved reviewer: anyone but the author", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState(later, "reviewer: UNRESOLVED", "poll-since: 2026-11-12T09:30:00Z", "ci-seen: "+testHead+" green")
		s.w.Reviews = arr(review(1, "alice", "COMMENTED", "2026-11-12T09:45:00Z", testHead, "self"))
		if got := s.svc.Tick(context.Background())[key]; got != OutIdle {
			t.Fatalf("author review triggered: %s", got)
		}
		s.w.Reviews = arr(review(2, "dave", "COMMENTED", "2026-11-12T09:45:00Z", testHead, "other"))
		if got := s.svc.Tick(context.Background())[key]; got != OutStarted {
			t.Fatalf("%s", got)
		}
	})
	t.Run("first sight sets poll-since", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState(later, "reviewer: bob")
		if got := s.svc.Tick(context.Background())[key]; got != OutIdle {
			t.Fatalf("%s", got)
		}
		d, _ := s.files().Read(Key{"acme", "app", 7})
		if d.Get("poll-since") != stamp(s.now) || d.Get("ci-seen") == "" {
			t.Fatalf("poll-since %q ci-seen %q", d.Get("poll-since"), d.Get("ci-seen"))
		}
	})
	t.Run("ci change triggers", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState(later, "reviewer: bob", "poll-since: 2026-11-12T09:30:00Z", "ci-seen: "+testHead+" pending")
		s.w.Checks = `[{"name":"build","state":"FAILURE","bucket":"fail","link":"x"}]`
		if got := s.svc.Tick(context.Background())[key]; got != OutStarted {
			t.Fatalf("%s", got)
		}
	})
	t.Run("dispatch lane owns it", func(t *testing.T) {
		s := newSrv(t, func(d *Deps) { d.Lanes = fakeLanes{owned: map[int]bool{7: true}} })
		s.seedState(due)
		if got := s.svc.Tick(context.Background())[key]; got != OutDispatch {
			t.Fatalf("%s", got)
		}
		d, _ := s.files().Read(Key{"acme", "app", 7})
		if d.Get("dispatch-due") == "" || d.Get("next-poll") != "2026-11-12T10:25:00Z" || len(s.ses.launched) != 0 {
			t.Fatalf("header %q %q", d.Get("dispatch-due"), d.Get("next-poll"))
		}
	})
	t.Run("MAX_GRINDS queues and leaves next-poll", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState(due)
		for i, pr := range []int{21, 22} {
			s.ses.add(sessions.Record{ID: "live" + itoa(i), Step: "pr-grind", Status: sessions.StRunning, Link: &sessions.Link{Owner: "acme", Repo: "other", Issue: pr}})
		}
		if got := s.svc.Tick(context.Background())[key]; got != OutQueued {
			t.Fatalf("%s", got)
		}
		d, _ := s.files().Read(Key{"acme", "app", 7})
		if d.Get("next-poll") != "2026-11-12T09:59:00Z" {
			t.Fatalf("next-poll moved: %q", d.Get("next-poll"))
		}
	})
	t.Run("no checkout is invalid", func(t *testing.T) {
		s := newSrv(t, func(d *Deps) { d.Products = fakeRepos{} })
		s.seedState(due)
		if got := s.svc.Tick(context.Background())[key]; got != OutInvalid {
			t.Fatalf("%s", got)
		}
	})
}

func snapOf(prs ...poller.OpenPR) poller.Snapshot {
	d := poller.EmptyData()
	d.OpenPRs = prs
	at := t0
	return poller.Snapshot{Repo: "acme/app", Data: d, FetchedAt: &at}
}

func dataOf(prs ...poller.OpenPR) poller.Data { return snapOf(prs...).Data }

func TestAutostart(t *testing.T) {
	draft := poller.OpenPR{N: 7, Draft: true, Refs: []int{3}}
	ready := poller.OpenPR{N: 7, Refs: []int{3}}
	run := func(s *srv, snap poller.Snapshot, prev poller.Data) int {
		for _, pr := range s.svc.turnedReady("acme/app", snap, prev) {
			_ = s.svc.autostart(context.Background(), "acme/app", pr)
		}
		return len(s.ses.started)
	}
	t.Run("draft to ready starts", func(t *testing.T) {
		s := newSrv(t, nil)
		if n := run(s, snapOf(ready), dataOf(draft)); n != 1 {
			t.Fatalf("started %d", n)
		}
		req := s.ses.started[0]
		if req.Step != "pr-grind" || req.Args != testPR || req.Repo != "acme/app" || !req.Guard {
			t.Fatalf("%+v", req)
		}
	})
	t.Run("first seen ready does not", func(t *testing.T) {
		s := newSrv(t, nil)
		if n := run(s, snapOf(ready), poller.EmptyData()); n != 0 {
			t.Fatal("started on first sight")
		}
		if n := run(s, snapOf(ready), dataOf(ready)); n != 0 {
			t.Fatal("started with no change")
		}
	})
	t.Run("stale data", func(t *testing.T) {
		s := newSrv(t, nil)
		snap := snapOf(ready)
		snap.Stale = true
		if n := run(s, snap, dataOf(draft)); n != 0 {
			t.Fatal("started on stale data")
		}
		snap = snapOf(ready)
		snap.FetchedAt = nil
		if n := run(s, snap, dataOf(draft)); n != 0 {
			t.Fatal("started before the first fetch")
		}
	})
	t.Run("a state file of any state", func(t *testing.T) {
		s := newSrv(t, nil)
		s.seedState("done: 2026-11-12T09:00:00Z - approved")
		if n := run(s, snapOf(ready), dataOf(draft)); n != 0 {
			t.Fatal("restarted a finished loop")
		}
	})
	t.Run("grinding off", func(t *testing.T) {
		s := newSrv(t, nil)
		_ = s.svc.d.Settings.SetIssueGrind("acme/app", 3, false) // the issue switch beats auto_grind
		if n := run(s, snapOf(ready), dataOf(draft)); n != 0 {
			t.Fatal("started with the issue switch off")
		}
		s = newSrv(t, nil)
		e := s.svc.d.Settings
		_ = e
		other := poller.OpenPR{N: 8, Refs: []int{4}}
		s.svc.d.Settings.SetIssueGrind("acme/app", 4, true)
		if n := run(s, snapOf(other), dataOf(poller.OpenPR{N: 8, Draft: true, Refs: []int{4}})); n != 1 {
			t.Fatal("issue switch on did not start")
		}
	})
	t.Run("repo auto_grind off", func(t *testing.T) {
		s := newSrv(t, nil)
		s.writeJSON("ui_settings.json", map[string]any{
			"reviewers": []any{map[string]string{"id": "r1", "name": "Bob", "slack_id": "UBOB000001", "github_login": "bob"}}, "active_reviewers": []string{"r1"},
			"repos": map[string]any{"acme/app": map[string]any{"auto_grind": false}},
		})
		s = &srv{env: s.env, ses: s.ses, note: s.note, svc: New(Deps{Home: s.h, GH: s.gh, Sessions: s.ses, Prompts: fakePrompts{}, Settings: settings.Open(s.h, nil)})}
		if n := run(s, snapOf(ready), dataOf(draft)); n != 0 {
			t.Fatal("started with auto_grind off")
		}
	})
	t.Run("dispatch lane owns the PR", func(t *testing.T) {
		s := newSrv(t, func(d *Deps) { d.Lanes = fakeLanes{owned: map[int]bool{7: true}} })
		if n := run(s, snapOf(ready), dataOf(draft)); n != 0 {
			t.Fatal("started a lane-owned PR")
		}
	})
	t.Run("resolver skip", func(t *testing.T) {
		s := newSrv(t, nil)
		s.writeJSON("ui_settings.json", map[string]any{"repos": map[string]any{"acme/app": map[string]any{"auto_grind": true}}})
		s.svc = New(Deps{Home: s.h, GH: s.gh, Sessions: s.ses, Prompts: fakePrompts{}, Settings: settings.Open(s.h, nil)})
		s.writeJSON("channels.json", map[string]any{})
		if n := run(s, snapOf(ready), dataOf(draft)); n != 0 {
			t.Fatal("started a repo with nobody to ask")
		}
	})
}

func TestStartGrindRefusals(t *testing.T) {
	s := newSrv(t, nil)
	s.w.Draft = true
	if _, err := s.svc.StartGrind(context.Background(), "acme/app", 7, "ui"); err == nil || !strings.Contains(err.Error(), "draft") {
		t.Fatalf("draft: %v", err)
	}
	s.w.Draft, s.w.State = false, "MERGED"
	if _, err := s.svc.StartGrind(context.Background(), "acme/app", 7, "ui"); err == nil {
		t.Fatal("merged PR started")
	}
	s.w.State = "OPEN"
	rec, err := s.svc.StartGrind(context.Background(), "acme/app", 7, "release")
	if err != nil || rec.ID == "" {
		t.Fatalf("%v %+v", err, rec)
	}
	if _, err := s.svc.StartGrind(context.Background(), "bad", 7, "ui"); err == nil {
		t.Fatal("bad slug accepted")
	}
}

func TestSkipCIAndStop(t *testing.T) {
	s := newSrv(t, nil)
	ctx := context.Background()
	if err := s.svc.SkipCI(ctx, "acme/app", 7); err == nil || !strings.Contains(err.Error(), "not paused") {
		t.Fatalf("no file: %v", err)
	}
	s.seedState("paused: 2026-11-12T09:00:00Z - CI red")
	if err := s.svc.SkipCI(ctx, "acme/app", 7); err == nil || !strings.Contains(err.Error(), "no finished grind session") {
		t.Fatalf("no session: %v", err)
	}
	s.ses.add(sessions.Record{ID: "fin", Step: "pr-grind", Status: sessions.StDone, SessionID: "claude-1", Link: &sessions.Link{Owner: "acme", Repo: "app", Issue: 7}})
	if err := s.svc.SkipCI(ctx, "acme/app", 7); err != nil {
		t.Fatal(err)
	}
	if len(s.ses.prompts) != 1 || s.ses.prompts[0][0] != "fin" || !strings.Contains(s.ses.prompts[0][1], "Skip CI for now") || !strings.Contains(s.ses.prompts[0][1], "PR #7") {
		t.Fatalf("%v", s.ses.prompts)
	}
	d, _ := s.files().Read(Key{"acme", "app", 7})
	if d.Get("paused") != "" {
		t.Fatal("paused not removed")
	}
	if err := s.svc.SkipCI(ctx, "acme/app", 7); err == nil {
		t.Fatal("skip-ci on a running loop")
	}

	if err := s.svc.Stop("acme/app", 7); err != nil {
		t.Fatal(err)
	}
	d, _ = s.files().Read(Key{"acme", "app", 7})
	first := d.Get("done")
	if !strings.HasSuffix(first, " - stopped from the UI") {
		t.Fatalf("done %q", first)
	}
	s.now = s.now.Add(time.Hour)
	if err := s.svc.Stop("acme/app", 7); err != nil {
		t.Fatal(err)
	}
	d, _ = s.files().Read(Key{"acme", "app", 7})
	if d.Get("done") != first {
		t.Fatal("stop rewrote done")
	}
	if err := s.svc.Stop("acme/app", 99); err == nil {
		t.Fatal("stop of unknown grind")
	}
}

func TestSetIssue(t *testing.T) {
	ready := poller.OpenPR{N: 7, Refs: []int{3}}
	s := newSrv(t, func(d *Deps) { d.Poller = fakeSnaps{snapOf(ready)} })
	if err := s.svc.SetIssue(context.Background(), "acme/app", 3, true); err != nil {
		t.Fatal(err)
	}
	if on, set := s.svc.d.Settings.IssueGrind("acme/app", 3); !on || !set {
		t.Fatal("switch not stored")
	}
	if len(s.ses.started) != 1 {
		t.Fatalf("started %d", len(s.ses.started))
	}
	s.seedState("next-poll: 2026-11-12T11:00:00Z")
	if err := s.svc.SetIssue(context.Background(), "acme/app", 3, false); err != nil {
		t.Fatal(err)
	}
	d, _ := s.files().Read(Key{"acme", "app", 7})
	if !strings.Contains(d.Get("done"), "stopped from the UI") {
		t.Fatalf("off did not stop: %q", d.Get("done"))
	}
	if err := s.svc.SetIssue(context.Background(), "acme/app", 0, true); err == nil {
		t.Fatal("issue 0 accepted")
	}
}

func TestNotifyScan(t *testing.T) {
	s := newSrv(t, nil)
	s.seedState("done: 2026-11-12T09:00:00Z - approved by bob")
	s.svc.NotifyScan() // first scan: silent
	if len(s.note.got) != 0 {
		t.Fatalf("first scan notified: %v", s.note.got)
	}
	if !fileExists(s.h.Path("grind_notified.json")) {
		t.Fatal("seen set not written")
	}
	s.svc.NotifyScan()
	if len(s.note.got) != 0 {
		t.Fatal("repeat scan notified")
	}
	_ = os.WriteFile(s.h.Path("pr-grind", "acme-app-8.md"), []byte(strings.Join([]string{
		"owner: acme", "repo: app", "number: 8", "thread: github", "paused: 2026-11-12T09:30:00Z - needs a human",
	}, "\n")+"\n"), 0o600)
	s.svc.NotifyScan()
	s.svc.NotifyScan()
	if len(s.note.got) != 1 || s.note.got[0] != "grind-paused acme/app#8:paused:needs a human" {
		t.Fatalf("%v", s.note.got)
	}
	n := s.note.note[0]
	if n.Text != "needs a human" || n.Link == nil || n.Link.Issue != 8 || n.Repo != "acme/app" || n.Command != "/pr-grind github" {
		t.Fatalf("%+v", n)
	}
	// resolved then paused again for the same reason notifies again
	_ = s.files().Update(Key{"acme", "app", 8}, t0, func(d *Doc) error { d.Del("paused"); return nil })
	s.svc.NotifyScan()
	_ = s.files().Update(Key{"acme", "app", 8}, t0, func(d *Doc) error {
		d.Set("paused", "2026-11-12T09:40:00Z - needs a human")
		return nil
	})
	s.svc.NotifyScan()
	if len(s.note.got) != 2 {
		t.Fatalf("%v", s.note.got)
	}
	// a done loop notifies once
	_ = s.files().Update(Key{"acme", "app", 8}, t0, func(d *Doc) error {
		d.Del("paused")
		d.Set("done", "2026-11-12T10:00:00Z - merged")
		return nil
	})
	s.svc.NotifyScan()
	s.svc.NotifyScan()
	if len(s.note.got) != 3 || s.note.got[2] != "grind-done acme/app#8:done" {
		t.Fatalf("%v", s.note.got)
	}
	var seen []string
	_ = home.ReadJSON(s.h.Path("grind_notified.json"), &seen)
	if len(seen) != 2 || seen[0] > seen[1] {
		t.Fatalf("seen %v", seen)
	}
}

func TestRoutes(t *testing.T) {
	s := newSrv(t, nil)
	s.seedState("paused: 2026-11-12T09:00:00Z - CI red")
	mux := http.NewServeMux()
	for _, r := range Routes(s.svc) {
		mux.Handle(r.Pattern, r.Handler)
	}
	do := func(method, path, body string) (int, map[string]any) {
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		if body != "" {
			req.Header.Set("Content-Type", "application/json")
		}
		rr := httptest.NewRecorder()
		mux.ServeHTTP(rr, req)
		var m map[string]any
		_ = json.Unmarshal(rr.Body.Bytes(), &m)
		return rr.Code, m
	}
	code, m := do("GET", "/api/grinds", "")
	gs, _ := m["grinds"].([]any)
	if code != 200 || len(gs) != 1 || gs[0].(map[string]any)["state"] != "paused" {
		t.Fatalf("%d %v", code, m)
	}
	if _, m = do("GET", "/api/grinds?repo=other/repo", ""); len(m["grinds"].([]any)) != 0 {
		t.Fatalf("filter %v", m)
	}
	if code, _ = do("POST", "/api/grinds", `{"repo":"acme/app","pr":7}`); code != 201 {
		t.Fatalf("start %d", code)
	}
	if code, _ = do("POST", "/api/grinds", `{"repo":"acme/app"}`); code != 400 {
		t.Fatalf("bad start %d", code)
	}
	if code, m = do("POST", "/api/grinds/acme/app/7/skip-ci", ""); code != 409 {
		t.Fatalf("skip-ci %d %v", code, m)
	}
	if code, _ = do("POST", "/api/grinds/issue", `{"repo":"acme/app","issue":3}`); code != 400 {
		t.Fatalf("issue without on %d", code)
	}
	if code, m = do("POST", "/api/grinds/issue", `{"repo":"acme/app","issue":3,"on":false}`); code != 200 || m["ok"] != true {
		t.Fatalf("issue %d %v", code, m)
	}
	if code, m = do("POST", "/api/grinds/acme/app/7/stop", ""); code != 200 || m["state"] != "done" {
		t.Fatalf("stop %d %v", code, m)
	}
	if code, _ = do("POST", "/api/grinds/acme/app/99/stop", ""); code != 404 {
		t.Fatalf("stop unknown %d", code)
	}
}
