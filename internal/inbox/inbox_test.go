package inbox

import (
	"context"
	"encoding/json"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/blubird"
	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/inbox/inboxtest"
	"github.com/masnun-siam/setu/internal/jev"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/products"
	"github.com/masnun-siam/setu/internal/sessions"
)

type fSessions struct{ recs []sessions.Record }

func (f fSessions) List(sessions.Filter) []sessions.Record { return f.recs }
func (f fSessions) Public(r sessions.Record) sessions.Session {
	s := sessions.Session{ID: r.ID, Title: r.Command, Link: r.Link, Status: r.Status, Account: r.ClaudeCmd}
	if r.Repo != "" {
		s.Repo = &r.Repo
	}
	return s
}

type fSnaps struct {
	m       map[string]poller.Snapshot
	viewed  []string
	watched []string
}

func (f *fSnaps) Snapshot(r string) poller.Snapshot {
	for k, v := range f.m {
		if strings.EqualFold(k, r) {
			return v
		}
	}
	return poller.Snapshot{Repo: r, Data: poller.EmptyData(), Stale: true}
}
func (f *fSnaps) MarkViewed(r string) { f.viewed = append(f.viewed, r) }
func (f *fSnaps) Watched() []string   { return f.watched }

type fProducts struct {
	ps   []products.Product
	repo []products.Repo
	prds map[string][]products.PRD
}

func (f fProducts) Products() []products.Product { return f.ps }
func (f fProducts) Repos() []products.Repo       { return f.repo }
func (f fProducts) PRDs(p string) ([]products.PRD, error) {
	return f.prds[p], nil
}

type fGH struct{ a gh.Auth }

func (f fGH) Get(context.Context) gh.Auth { return f.a }

type fBlubird struct{ s blubird.Status }

func (f fBlubird) Status() blubird.Status { return f.s }

type fGrindSet struct{ on map[string]bool }

func (f fGrindSet) GrindOn(slug string, issue int) bool { return f.on[slug] }

type fGrinds []GrindStatus

func (f fGrinds) Index() []GrindStatus { return f }

type fDispatch struct {
	ds    []Dispatch
	owned map[string]bool
}

func (f fDispatch) List() []Dispatch { return f.ds }
func (f fDispatch) Owned(repo string, issue, pr int) bool {
	return f.owned[repo+"#"+itoa(issue)] || f.owned[repo+"#"+itoa(pr)]
}

func itoa(n int) string { return strconv.Itoa(n) }

type fAway struct{ a Away }

func (f fAway) Public() Away { return f.a }

type fPanels []Panel

func (f fPanels) List() []Panel { return f }

type fReleases struct{ l []Release }

func (f fReleases) List(string) []Release      { return f.l }
func (f fReleases) Repos(string) []ReleaseRepo { return nil }

type fCleanup map[string]map[int]products.CleanupFlags

func (f fCleanup) Flags(r string) map[int]products.CleanupFlags { return f[r] }

func now() time.Time { return time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC) }

func fresh(repo string, d poller.Data) poller.Snapshot {
	t := now()
	return poller.Snapshot{Repo: repo, Data: d, FetchedAt: &t}
}

func pending(id string) *sessions.Round {
	return &sessions.Round{ID: "r1", Status: "pending", Questions: []sessions.Question{{Question: "Which column?"}}}
}

func rec(id string, st sessions.Status, started string) sessions.Record {
	return sessions.Record{ID: id, Command: "/blubird:implement-issue 5", Repo: "acme/api", Status: st, StartedAt: started,
		Link: &sessions.Link{Owner: "acme", Repo: "api", Issue: 5}}
}

func byType(l List) map[string]Item {
	m := map[string]Item{}
	for _, it := range l.Items {
		m[it.Type] = it
	}
	return m
}

func TestEveryKeptType(t *testing.T) {
	w := rec("20261112T090000000001Z-aaaaaaaa", sessions.StWaiting, "2026-11-12T09:00:00Z")
	w.PendingQuestion = pending("r1")
	f := rec("20261112T080000000001Z-bbbbbbbb", sessions.StFailed, "2026-11-12T08:00:00Z")
	f.Command, f.Error, f.EndedAt = "/blubird:verifier-locally 7", "phpstan failed", "2026-11-12T08:30:00Z"
	lim := rec("20261112T070000000001Z-cccccccc", sessions.StLimited, "2026-11-12T07:00:00Z")
	lim.Command, lim.LimitResetsAt = "/blubird:refine-issues 9", now().Add(time.Hour).Unix()
	q := rec("20261112T060000000001Z-dddddddd", sessions.StQueued, "2026-11-12T06:00:00Z")
	q.Command, q.Note = "/blubird:docs-updater", "batch cap"

	conflict := poller.OpenPR{N: 11, Title: "conflicting", URL: "https://github.com/acme/api/pull/11", Conflict: true, Refs: []int{5}}
	ready := poller.OpenPR{N: 12, Title: "ready", URL: "https://github.com/acme/api/pull/12", SHA: strings.Repeat("a", 40), CI: "success", Approved: true, Refs: []int{6}, Checks: 3}
	snaps := &fSnaps{m: map[string]poller.Snapshot{"acme/api": fresh("acme/api", poller.Data{
		Issues: []poller.Issue{{N: 5}, {N: 6}}, OpenPRs: []poller.OpenPR{conflict, ready}, Merged: []poller.Merged{}, ClosedEpics: []poller.ClosedEpic{}})},
		watched: []string{"acme/api", "acme/web"}}
	end := int64(1)
	lane := func(suffix string) Lane {
		return Lane{Key: "acme/api#" + suffix, Repo: "acme/api", N: 20, Title: "lane"}
	}
	lneeds, lheld, lmerge, llim, lstall := lane("20"), lane("21"), lane("22"), lane("23"), lane("24")
	ns, hd, st := "decide the schema", "CI stuck", "stopped before a PR"
	lneeds.NeedsYou, lheld.Held, lstall.Stalled = &ns, &hd, &st
	lmerge.Stage = "awaiting_merge"
	pr := 40
	lmerge.PR = &pr
	until := now().Add(time.Hour).Unix()
	llim.LimitedUntil = &until
	endAt := now().Add(-time.Hour).Unix()
	_ = end
	note := "@here release"
	pn := 7

	b := New(Deps{
		Sessions:  fSessions{[]sessions.Record{w, f, lim, q}},
		Snapshots: snaps,
		Products: fProducts{
			ps:   []products.Product{{DocsRepo: "acme/docs", Repos: []products.ProductRepo{{Repo: "acme/api"}}}},
			repo: []products.Repo{{Slug: "acme/api"}, {Slug: "local/scratch", Path: "/x"}},
			prds: map[string][]products.PRD{"acme/docs": {{Title: "Payouts", Status: "In review", Path: "docs/prds/pay.md"}, {Title: "Draft", Status: "Draft", Path: "docs/prds/d.md"}}},
		},
		GH:       fGH{gh.Auth{OK: false, Error: "not logged in"}},
		Blubird:  fBlubird{blubird.Status{Installed: false}},
		Settings: fGrindSet{},
		Grinds:   fGrinds{{Repo: "acme/api", PR: 12, State: "paused", Rounds: 2, Reason: sp("2026-11-12T09:30:00Z — reviewer silent")}},
		Dispatch: fDispatch{ds: []Dispatch{
			{ID: "d1", State: "running", Lanes: []Lane{lneeds, lheld, lmerge, llim, lstall}},
			{ID: "d2", State: "done", Title: "Epic", EndedAt: &endAt},
		}},
		Away: fAway{Away{Summary: &struct {
			Started int64             `json:"started"`
			Ended   int64             `json:"ended"`
			Held    int               `json:"held"`
			Log     []json.RawMessage `json:"log"`
		}{Ended: endAt, Held: 2}}},
		Panels: fPanels{
			{ID: "p-20261112T090000Z-aaaaaa", Repo: "acme/docs", Artifact: "/r/docs/prds/cap.md", State: "cap reached", Round: 3, MaxRounds: 3},
			{ID: "p-20261112T090000Z-bbbbbb", Repo: "acme/docs", Artifact: "/r/docs/prds/ok.md", State: "approved"},
		},
		PRDStatus: func(string) string { return "Draft" },
		Releases:  fReleases{[]Release{{ID: "r-1", Repo: "acme/api", Stage: "notify", Note: &note, PR: &pn, UpdatedAt: "2026-11-12T09:00:00Z"}}},
		Cleanup:   fCleanup{"acme/api": {5: {Uncommitted: []string{"a.go"}}}},
		Now:       now,
	})
	// the grind on PR 12 is paused, so pr_ready is blocked only if grind on; settings off -> ready
	l := b.Build(context.Background(), "", "")
	got := map[string]bool{}
	for _, it := range l.Items {
		got[it.Type] = true
		if len(it.Actions) == 0 {
			t.Errorf("%s has no action", it.Key)
		}
		for _, a := range it.Actions {
			if a.Open != "" {
				continue
			}
			if !inboxtest.Known(a.Method, a.Path) {
				t.Errorf("%s: action %s %s is not in API.md", it.Key, a.Method, a.Path)
			}
		}
		keys := map[string]bool{}
		for _, a := range it.Actions {
			if keys[a.Key] {
				t.Errorf("%s: duplicate action key %q", it.Key, a.Key)
			}
			keys[a.Key] = true
		}
	}
	if inboxtest.Count() == 0 {
		t.Fatal("API.md not found")
	}
	for _, ty := range []string{TGHAuth, TBlubirdMissing, TQuestion, TPRDApproval, TSessionFailed, TLimited, TQueued, TReviewCap,
		TReviewApproved, TGrindPaused, TNeedsCleanup, TPRConflict, TPRReady, TReleaseNote, TDispatchNeeds, TDispatchHeld,
		TDispatchStalled, TDispatchMerge, TDispatchLimited, TDispatchDone, TAwaySummary, TRepoUnpublished} {
		if !got[ty] {
			t.Errorf("missing item type %s", ty)
		}
	}
	m := byType(l)
	if s := m[TDispatchStalled]; s.Key != "dispatch:d1:acme/api#24:stalled" || s.Group != GFix || s.Detail[0] != "Stalled: stopped before a PR" {
		t.Errorf("stalled lane: %+v", s)
	}
	if a := m[TDispatchStalled].Actions; len(a) != 3 || a[0].Key != "c" || !a[0].Primary || !a[0].Clears || a[0].Method != "POST" ||
		a[0].Path != "/api/dispatches/d1/lane" || a[0].Body.(map[string]any)["action"] != "continue" || a[0].Body.(map[string]any)["lane"] != "acme/api#24" ||
		a[1].Key != "r" || a[1].Primary || a[2].Key != "o" {
		t.Errorf("stalled lane actions: %+v", a)
	}
	for _, it := range l.Items {
		if it.Key == "dispatch:d1:acme/api#24:needs" {
			t.Errorf("a stalled lane has no needs row")
		}
	}
	if m[TGrindPaused].Detail[0] != "reviewer silent" || *m[TGrindPaused].At != "2026-11-12T09:30:00Z" {
		t.Errorf("grind item: %+v", m[TGrindPaused])
	}
	if m[TQuestion].Round == nil || m[TQuestion].SessionID != w.ID {
		t.Errorf("question: %+v", m[TQuestion])
	}
	if m[TPRConflict].Key != "pr_conflict:acme/api#11" || m[TPRReady].Key != "pr_ready:acme/api#12" {
		t.Errorf("keys: %s %s", m[TPRConflict].Key, m[TPRReady].Key)
	}
	// count excludes wait
	wait := 0
	for _, it := range l.Items {
		if it.Group == GWait {
			wait++
		}
	}
	if l.Count != len(l.Items)-wait || wait != 3 {
		t.Errorf("count %d items %d wait %d", l.Count, len(l.Items), wait)
	}
	// stale: acme/web has no snapshot, docs has none
	if strings.Join(l.Stale, ",") != "acme/docs,acme/web" {
		t.Errorf("stale %v", l.Stale)
	}
	// rank: group order
	prev := -1
	for _, it := range l.Items {
		if groupOrder[it.Group] < prev {
			t.Fatalf("not ranked: %s after group index %d", it.Key, prev)
		}
		prev = groupOrder[it.Group]
	}
	if l.Items[0].Group != GBlock {
		t.Errorf("block first, got %s", l.Items[0].Key)
	}
}

func TestFailedOnlyNewestAndNotDismissed(t *testing.T) {
	old := rec("20261112T010000000001Z-aaaaaaaa", sessions.StFailed, "2026-11-12T01:00:00Z")
	newer := rec("20261112T020000000001Z-bbbbbbbb", sessions.StDone, "2026-11-12T02:00:00Z")
	lens := rec("20261112T030000000001Z-cccccccc", sessions.StFailed, "2026-11-12T03:00:00Z")
	lens.PanelRole, lens.Command = "lens", "/peer"
	dis := rec("20261112T040000000001Z-dddddddd", sessions.StFailed, "2026-11-12T04:00:00Z")
	dis.Command, dis.Dismissed = "/other", true
	ans := rec("20261112T050000000001Z-eeeeeeee", sessions.StWaiting, "2026-11-12T05:00:00Z")
	ans.Role, ans.PendingQuestion, ans.Command = "away-answerer", pending("x"), "/ans"
	b := New(Deps{Sessions: fSessions{[]sessions.Record{old, newer, lens, dis, ans}}, Now: now})
	if l := b.Build(context.Background(), "", ""); len(l.Items) != 0 {
		t.Fatalf("expected nothing, got %+v", l.Items)
	}
}

func TestRepoFilterAndGlobalItemsStay(t *testing.T) {
	snaps := &fSnaps{m: map[string]poller.Snapshot{
		"acme/api": fresh("acme/api", poller.Data{OpenPRs: []poller.OpenPR{{N: 1, Conflict: true, URL: "u"}}, Issues: []poller.Issue{}}),
		"acme/web": fresh("acme/web", poller.Data{OpenPRs: []poller.OpenPR{{N: 2, Conflict: true, URL: "u"}}, Issues: []poller.Issue{}}),
	}, watched: []string{"acme/api", "acme/web"}}
	b := New(Deps{Snapshots: snaps, GH: fGH{gh.Auth{Error: "x"}}, Now: now,
		Products: fProducts{repo: []products.Repo{{Slug: "acme/api"}, {Slug: "acme/web"}}}})
	l := b.Build(context.Background(), "", "ACME/web")
	var keys []string
	for _, it := range l.Items {
		keys = append(keys, it.Key)
	}
	if strings.Join(keys, ",") != "gh_auth,pr_conflict:acme/web#2" {
		t.Fatalf("keys %v", keys)
	}
	if len(l.Stale) != 0 {
		t.Fatalf("stale %v", l.Stale)
	}
}

func TestReadyGatesAndDispatchOwnership(t *testing.T) {
	mk := func(n int, mod func(*poller.OpenPR)) poller.OpenPR {
		p := poller.OpenPR{N: n, CI: "success", Approved: true, URL: "u", SHA: strings.Repeat("b", 40), Refs: []int{n}}
		mod(&p)
		return p
	}
	prs := []poller.OpenPR{
		mk(1, func(p *poller.OpenPR) {}),
		mk(2, func(p *poller.OpenPR) { p.Draft = true }),
		mk(3, func(p *poller.OpenPR) { p.CI = "pending" }),
		mk(4, func(p *poller.OpenPR) { p.ThreadsOpen = 1 }),
		mk(5, func(p *poller.OpenPR) { p.Approved = false }),
		mk(6, func(p *poller.OpenPR) {}),
		mk(7, func(p *poller.OpenPR) {}),
	}
	snaps := &fSnaps{m: map[string]poller.Snapshot{"acme/api": fresh("acme/api", poller.Data{OpenPRs: prs, Issues: []poller.Issue{}})}, watched: []string{"acme/api"}}
	b := New(Deps{
		Snapshots: snaps, GH: fGH{gh.Auth{OK: true, Login: "someone"}}, Now: now,
		Settings: fGrindSet{on: map[string]bool{"acme/api": true}},
		Grinds:   fGrinds{{Repo: "acme/api", PR: 6, State: "approved"}, {Repo: "acme/api", PR: 7, State: "running"}},
		Dispatch: fDispatch{owned: map[string]bool{"acme/api#1": true}},
	})
	// grinding is on for the repo: PR 1 has no grind (not ready), PR 6 grind approved (ready), 7 running
	l := b.Build(context.Background(), "", "")
	var keys []string
	for _, it := range l.Items {
		keys = append(keys, it.Key)
	}
	if strings.Join(keys, ",") != "pr_ready:acme/api#6" {
		t.Fatalf("keys %v", keys)
	}
	// solo owner skips the approval rule
	b2 := New(Deps{Snapshots: snaps, GH: fGH{gh.Auth{OK: true, Login: "acme"}}, Now: now})
	l2 := b2.Build(context.Background(), "", "")
	var k2 []string
	for _, it := range l2.Items {
		k2 = append(k2, it.Key)
	}
	if strings.Join(k2, ",") != "pr_ready:acme/api#1,pr_ready:acme/api#5,pr_ready:acme/api#6,pr_ready:acme/api#7" {
		t.Fatalf("solo keys %v", k2)
	}
}

func TestStaleSnapshotContributesNoPollerItems(t *testing.T) {
	s := fresh("acme/api", poller.Data{OpenPRs: []poller.OpenPR{{N: 1, Conflict: true}}, Issues: []poller.Issue{}})
	s.Stale = true
	snaps := &fSnaps{m: map[string]poller.Snapshot{"acme/api": s}, watched: []string{"acme/api"}}
	b := New(Deps{Snapshots: snaps, Grinds: fGrinds{{Repo: "acme/api", PR: 3, State: "paused"}}, Now: now})
	l := b.Build(context.Background(), "", "")
	if len(l.Items) != 1 || l.Items[0].Type != TGrindPaused || l.Items[0].Links.Issue != "" {
		t.Fatalf("items %+v", l.Items)
	}
	if len(l.Stale) != 1 {
		t.Fatalf("stale %v", l.Stale)
	}
	// a fresh snapshot without that PR drops the paused grind
	snaps.m["acme/api"] = fresh("acme/api", poller.Data{Issues: []poller.Issue{}})
	if l := b.Build(context.Background(), "", ""); len(l.Items) != 0 {
		t.Fatalf("items %+v", l.Items)
	}
}

func TestDispatchDropsOwnedRowsAndDoneWindow(t *testing.T) {
	f := rec("20261112T080000000001Z-bbbbbb11", sessions.StFailed, "2026-11-12T08:00:00Z")
	old := now().Add(-30 * 24 * time.Hour).Unix()
	b := New(Deps{Sessions: fSessions{[]sessions.Record{f}}, Now: now,
		Dispatch: fDispatch{owned: map[string]bool{"acme/api#5": true}, ds: []Dispatch{{ID: "d", State: "done", EndedAt: &old}, {ID: "e", State: "done", SeenDone: true, EndedAt: &old}}}})
	if l := b.Build(context.Background(), "", ""); len(l.Items) != 0 {
		t.Fatalf("items %+v", l.Items)
	}
}

func TestRankUrgencyThenTime(t *testing.T) {
	u := func(n int) *int { return &n }
	items := []Item{
		{Key: "a", Group: GFix, At: sp("2026-11-12T01:00:00Z")},
		{Key: "b", Group: GFix, At: sp("2026-11-12T02:00:00Z")},
		{Key: "c", Group: GFix, Urgency: u(4), At: sp("2026-11-11T00:00:00Z")},
		{Key: "d", Group: GAnswer},
		{Key: "e", Group: GBlock},
		{Key: "f", Group: GFix},
		{Key: "g", Group: GWait},
		{Key: "h", Group: GSetup},
		{Key: "i", Group: GDecide},
	}
	Rank(items)
	var ks []string
	for _, it := range items {
		ks = append(ks, it.Key)
	}
	if got := strings.Join(ks, ""); got != "edicbafhg" {
		t.Fatalf("rank %s", got)
	}
}

func TestUrgencyMapping(t *testing.T) {
	for in, want := range map[float64]int{-1: 1, 0: 1, 0.49: 1, 0.5: 2, 1.4: 2, 2.5: 4, 3.6: 5, 9: 5} {
		if got := UrgencyOf(in); got != want {
			t.Errorf("UrgencyOf(%v)=%d want %d", in, got, want)
		}
	}
}

type fJev struct {
	status string
	cache  map[string]float64
	asked  []string
	spent  int
}

func (j *fJev) Status() string { return j.status }
func (j *fJev) Peek(_, _, _, text string, _ map[string]string, _ []string) *jev.Answer {
	if s, ok := j.cache[text]; ok {
		return &jev.Answer{Status: "ok", Score: s}
	}
	return nil
}
func (j *fJev) Ask(_ context.Context, _, _, _, text string, _ map[string]string, _ []string) jev.Answer {
	j.asked = append(j.asked, text)
	j.cache[text] = 3
	return jev.Answer{Status: "ok", Score: 3}
}
func (j *fJev) Spent() int { return j.spent }

func TestUrgencyScannerAndPeek(t *testing.T) {
	f1 := rec("20261112T010000000001Z-aaaaaaaa", sessions.StFailed, "2026-11-12T01:00:00Z")
	f1.Command, f1.Error = "/a", "boom one"
	f2 := rec("20261112T020000000001Z-bbbbbbbb", sessions.StFailed, "2026-11-12T02:00:00Z")
	f2.Command, f2.Error = "/b", "boom two"
	j := &fJev{status: "ok", cache: map[string]float64{"boom one": 1}}
	b := New(Deps{Sessions: fSessions{[]sessions.Record{f1, f2}}, Jev: j, Now: now})
	l := b.Build(context.Background(), "", "")
	if l.Items[0].Key != "failed:"+f1.ID || *l.Items[0].Urgency != 2 || l.Items[1].Urgency != nil {
		t.Fatalf("peek ranking: %+v", l.Items)
	}
	if !b.urg.scan(context.Background()) || len(j.asked) != 1 || j.asked[0] != "boom two" {
		t.Fatalf("asked %v", j.asked)
	}
	l = b.Build(context.Background(), "", "")
	if *l.Items[0].Urgency != 4 || l.Items[0].Key != "failed:"+f2.ID {
		t.Fatalf("after scoring: %+v", l.Items)
	}
	j.spent = 400
	j.cache = map[string]float64{}
	if b.urg.scan(context.Background()) {
		t.Fatal("scan must skip at 400 calls/hour")
	}
	j.spent, j.status = 0, "off"
	if b.urg.scan(context.Background()) {
		t.Fatal("scan must skip when jev is off")
	}
}

func TestStartPublishesOnlyOnChange(t *testing.T) {
	bus := events.New()
	ch, cancel := bus.Subscribe(16)
	defer cancel()
	ss := &mutSessions{}
	b := New(Deps{Sessions: ss, Bus: bus, Now: now})
	ctx, stop := context.WithCancel(context.Background())
	defer stop()
	b.Start(ctx)
	time.Sleep(50 * time.Millisecond)
	bus.Publish(events.TSessions, map[string]any{"id": "x"}) // nothing changed -> no inbox event
	expect := func(want bool) {
		t.Helper()
		deadline := time.After(1200 * time.Millisecond)
		for {
			select {
			case e := <-ch:
				if e.Topic == events.TInbox {
					if !want {
						t.Fatalf("unexpected inbox event %v", e.Data)
					}
					return
				}
			case <-deadline:
				if want {
					t.Fatal("no inbox event")
				}
				return
			}
		}
	}
	expect(false)
	ss.set(sessions.Record{ID: "20261112T010000000001Z-aaaaaaaa", Command: "/a", Status: sessions.StFailed, StartedAt: "2026-11-12T01:00:00Z", Error: "x"})
	bus.Publish(events.TSessions, map[string]any{"id": "x"})
	expect(true)
}

type mutSessions struct {
	mu   sync.Mutex
	recs []sessions.Record
}

func (m *mutSessions) set(r sessions.Record) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.recs = append(m.recs, r)
}
func (m *mutSessions) List(sessions.Filter) []sessions.Record {
	m.mu.Lock()
	defer m.mu.Unlock()
	return append([]sessions.Record(nil), m.recs...)
}
func (m *mutSessions) Public(r sessions.Record) sessions.Session {
	return sessions.Session{ID: r.ID, Title: r.Command, Status: r.Status}
}
