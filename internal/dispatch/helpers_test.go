package dispatch

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/gh/ghtest"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/notify"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
	"github.com/masnun-siam/setu/internal/settings"
)

// ---- fakes ----

type sentMsg struct{ ID, Text string }

type fakeSessions struct {
	mu        sync.Mutex
	recs      map[string]*sessions.Record
	Launched  []sessions.Spec
	Sent      []sentMsg
	Stopped   []string
	LaunchErr error
	SendErr   error
	seq       int
}

func newFakeSessions() *fakeSessions { return &fakeSessions{recs: map[string]*sessions.Record{}} }

func (f *fakeSessions) Launch(_ context.Context, s sessions.Spec) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.LaunchErr != nil {
		return sessions.Record{}, f.LaunchErr
	}
	f.seq++
	id := fmt.Sprintf("S%d", f.seq)
	r := &sessions.Record{ID: id, Status: sessions.StRunning, Command: s.Prompt.Display}
	f.recs[id] = r
	f.Launched = append(f.Launched, s)
	return *r, nil
}

func (f *fakeSessions) Get(id string) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r, ok := f.recs[id]
	if !ok {
		return sessions.Record{}, errs.NotFound("no session %s", id)
	}
	return *r, nil
}

func (f *fakeSessions) Update(id string, fn func(*sessions.Record) error) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	r, ok := f.recs[id]
	if !ok {
		return sessions.Record{}, errs.NotFound("no session %s", id)
	}
	err := fn(r)
	return *r, err
}

func (f *fakeSessions) SendPrompt(_ context.Context, id, text string, _ int) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.SendErr != nil {
		return "", f.SendErr
	}
	f.Sent = append(f.Sent, sentMsg{id, text})
	return "sent", nil
}

func (f *fakeSessions) Stop(_ context.Context, id string) (sessions.Record, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.Stopped = append(f.Stopped, id)
	r, ok := f.recs[id]
	if !ok {
		return sessions.Record{}, errs.NotFound("no session %s", id)
	}
	r.Status = sessions.StStopped
	return *r, nil
}

func (f *fakeSessions) List(sessions.Filter) []sessions.Record {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []sessions.Record
	for _, r := range f.recs {
		out = append(out, *r)
	}
	return out
}

func (f *fakeSessions) set(id string, fn func(*sessions.Record)) {
	f.mu.Lock()
	defer f.mu.Unlock()
	fn(f.recs[id])
}

type fakePrompts struct{ Unavailable error }

func (p fakePrompts) BuildIn(step, args, repo string) (prompts.Prompt, error) {
	cmd := "/blubird:" + step
	if step == "pr-grind" {
		cmd = "/pr-grind"
	}
	t := strings.TrimSpace(cmd + " " + args)
	return prompts.Prompt{Step: step, Display: t, Text: t}, nil
}
func (p fakePrompts) Available(string) error { return p.Unavailable }

type fakeSnaps struct {
	mu sync.Mutex
	m  map[string]poller.Snapshot
}

func (f *fakeSnaps) Snapshot(repo string) poller.Snapshot {
	f.mu.Lock()
	defer f.mu.Unlock()
	if s, ok := f.m[repo]; ok {
		return s
	}
	return poller.Snapshot{Repo: repo, Stale: true}
}

func (f *fakeSnaps) set(repo string, d poller.Data) {
	f.mu.Lock()
	defer f.mu.Unlock()
	t := time.Now()
	if f.m == nil {
		f.m = map[string]poller.Snapshot{}
	}
	f.m[repo] = poller.Snapshot{Repo: repo, Data: d, FetchedAt: &t}
}

type fakeNotifier struct {
	mu    sync.Mutex
	Notes []notify.Note
}

func (n *fakeNotifier) Notify(event string, note notify.Note) {
	n.mu.Lock()
	defer n.mu.Unlock()
	if event == "dispatch" {
		n.Notes = append(n.Notes, note)
	}
}

type fakeAccounts struct{ labels map[string]string }

func (a fakeAccounts) Account(l string) (settings.Account, bool) {
	c, ok := a.labels[l]
	return settings.Account{Label: l, Cmd: c}, ok
}
func (a fakeAccounts) Default() settings.Account {
	return settings.Account{Label: "claude", Cmd: "claude"}
}

type clock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *clock) Now() time.Time { c.mu.Lock(); defer c.mu.Unlock(); return c.t }
func (c *clock) add(d time.Duration) {
	c.mu.Lock()
	c.t = c.t.Add(d)
	c.mu.Unlock()
}

type mergeCall struct {
	Repo string
	PR   int
	SHA  string
}

type env struct {
	t     *testing.T
	h     *home.Home
	svc   *Service
	sess  *fakeSessions
	snaps *fakeSnaps
	gh    *ghtest.Client
	note  *fakeNotifier
	clk   *clock

	mergeOK  bool
	mergeErr string
	merges   []mergeCall
	grind    GrindPlan
}

func newEnv(t *testing.T) *env {
	t.Helper()
	root := t.TempDir()
	t.Setenv("HOME", root)
	t.Setenv("SETU_HOME", filepath.Join(root, ".setu"))
	h := &home.Home{Root: filepath.Join(root, ".setu")}
	e := &env{t: t, h: h, sess: newFakeSessions(), snaps: &fakeSnaps{}, gh: ghtest.New(), note: &fakeNotifier{},
		clk: &clock{t: time.Unix(1_800_000_000, 0)}, mergeOK: true, grind: GrindPlan{Path: "slack", Channel: "C1"}}
	e.svc = New(Deps{Home: h, GH: e.gh, Sessions: e.sess, Prompts: fakePrompts{}, Snapshots: e.snaps,
		Accounts: fakeAccounts{labels: map[string]string{"work": "cc-work"}}, Notify: e.note, Now: e.clk.Now,
		Grind: func(string) GrindPlan { return e.grind },
		Login: func(context.Context) string { return "someone" },
		Merge: func(_ context.Context, repo string, pr int, sha string) (bool, string) {
			e.merges = append(e.merges, mergeCall{repo, pr, sha})
			return e.mergeOK, e.mergeErr
		},
		CoordRoot: filepath.Join(root, "coord")})
	return e
}

func (e *env) ctx() context.Context { return context.Background() }

// seed saves a running dispatch holding the lanes.
func (e *env) seed(settingsFn func(*store.Settings), lanes ...*store.Lane) *store.Dispatch {
	e.t.Helper()
	d := &store.Dispatch{ID: "aaaaaaaaaaaa", Title: "T", Runner: "headless", State: store.Running, Settings: store.Defaults(),
		Lanes: map[string]*store.Lane{}, CreatedAt: epoch(e.clk.Now()), SyncedAt: epoch(e.clk.Now())}
	epic := "o/r#1"
	d.Epic = &epic
	if settingsFn != nil {
		settingsFn(&d.Settings)
	}
	for _, l := range lanes {
		if l.Deps == nil {
			l.Deps = []string{}
		}
		d.Lanes[l.Key()] = l
	}
	if err := store.Save(e.h, d); err != nil {
		e.t.Fatal(err)
	}
	return d
}

func (e *env) load() store.Dispatch {
	e.t.Helper()
	d, err := store.Load(e.h, "aaaaaaaaaaaa")
	if err != nil {
		e.t.Fatal(err)
	}
	return d
}

func (e *env) tick() []store.Event {
	e.t.Helper()
	evs, err := e.svc.TickOne(e.ctx(), "aaaaaaaaaaaa")
	if err != nil {
		e.t.Fatal(err)
	}
	return evs
}

func (e *env) lane(n int) *store.Lane {
	e.t.Helper()
	d := e.load()
	l := d.Lanes[fmt.Sprintf("o/r#%d", n)]
	if l == nil {
		e.t.Fatalf("no lane %d in %v", n, d.SortedKeys())
	}
	return l
}

func evKinds(evs []store.Event) string {
	var out []string
	for _, e := range evs {
		out = append(out, e.Kind+":"+e.Text)
	}
	return strings.Join(out, " | ")
}

func (e *env) writeGrind(pr int, body string) {
	dir := e.h.Path("pr-grind")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		e.t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, fmt.Sprintf("o-r-%d.md", pr)), []byte(body), 0o644); err != nil {
		e.t.Fatal(err)
	}
}

func issue(n int, labels []string, prs ...poller.PR) poller.Issue {
	return poller.Issue{N: n, Title: fmt.Sprintf("issue %d", n), State: "OPEN", Labels: labels, PRs: prs,
		BlockedBy: []poller.Blocker{}, SubIssues: []poller.Ref{}, ClosedSubs: []poller.ClosedSub{}}
}

func data(issues []poller.Issue, open []poller.OpenPR, merged ...poller.Merged) poller.Data {
	d := poller.EmptyData()
	d.Issues = append(d.Issues, issues...)
	d.OpenPRs = append(d.OpenPRs, open...)
	d.Merged = append(d.Merged, merged...)
	return d
}
