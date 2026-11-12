package views

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

	"github.com/masnun-siam/setu/internal/blubird"
	"github.com/masnun-siam/setu/internal/claude"
	"github.com/masnun-siam/setu/internal/gh"
	"github.com/masnun-siam/setu/internal/home"
	"github.com/masnun-siam/setu/internal/inbox"
	"github.com/masnun-siam/setu/internal/inbox/inboxtest"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/products"
	"github.com/masnun-siam/setu/internal/prompts"
	"github.com/masnun-siam/setu/internal/sessions"
	"github.com/masnun-siam/setu/internal/settings"
)

var nowT = time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC)

func now() time.Time { return nowT }

type fSess struct {
	recs   []sessions.Record
	limits map[string]sessions.Limit
}

func (f fSess) List(fl sessions.Filter) []sessions.Record {
	var out []sessions.Record
	for _, r := range f.recs {
		if fl.Step != "" && stepOf(r) != fl.Step {
			continue
		}
		out = append(out, r)
	}
	return out
}
func stepOf(r sessions.Record) string { return r.Step }
func (f fSess) Public(r sessions.Record) sessions.Session {
	s := sessions.Session{ID: r.ID, Title: r.Command, Link: r.Link, Status: r.Status, StartedAt: r.StartedAt, Cost: r.Cost,
		PendingQuestion: r.PendingQuestion, Account: r.ClaudeCmd}
	if r.Step != "" {
		st, sk := r.Step, "blubird:"+r.Step
		s.Step, s.Skill = &st, &sk
	}
	if r.Repo != "" {
		rr := r.Repo
		s.Repo = &rr
	}
	if r.EndedAt != "" {
		e := r.EndedAt
		s.EndedAt = &e
	}
	return s
}
func (f fSess) Stats() sessions.SessionStats {
	return sessions.SessionStats{MonthCount: 3, MonthCost: 4.5}
}
func (f fSess) Limits() map[string]sessions.Limit { return f.limits }

type fSteps []prompts.Step

func (f fSteps) Steps() []prompts.Step { return f }
func (f fSteps) Step(id string) (prompts.Step, bool) {
	for _, s := range f {
		if s.ID == id {
			return s, true
		}
	}
	return prompts.Step{}, false
}

var steps = fSteps{
	{ID: "create-prd", Source: "blubird", Skill: "create-prd", RunsIn: prompts.InDocs, Stage: "prd", Label: "Create PRD"},
	{ID: "refine-issues", Source: "blubird", Skill: "refine-issues", RunsIn: prompts.InIssue, Stage: "refine", Label: "Refine issues"},
	{ID: "implement-issue", Source: "blubird", Skill: "implement-issue", RunsIn: prompts.InIssue, Stage: "implement", Label: "Implement issue"},
	{ID: "verifier-locally", Source: "blubird", Skill: "verifier-locally", RunsIn: prompts.InIssue, Stage: "implement", Label: "Verify"},
	{ID: "map-prds", Source: "blubird", Skill: "map-prds", RunsIn: prompts.InDocs, Stage: "prd,ops", Label: "Map PRDs"},
	{ID: "agentic-onboard", Source: "blubird", Skill: "agentic-onboard", RunsIn: prompts.InRepo, Stage: "ops", Label: "Agentic onboard"},
	{ID: "skill-feedback", Source: "blubird", Skill: "skill-feedback", RunsIn: prompts.InRepo, Stage: "ops", Label: "Skill feedback"},
	{ID: "day-end-reconcile", Source: "blubird", Skill: "day-end-reconcile", RunsIn: prompts.InNone, Stage: "me", Label: "Day end"},
	{ID: "weekly-review", Source: "blubird", Skill: "weekly-review", RunsIn: prompts.InNone, Stage: "me", Label: "Weekly"},
}

type fSnaps struct {
	m      map[string]poller.Snapshot
	viewed []string
}

func (f *fSnaps) Snapshot(r string) poller.Snapshot {
	if s, ok := f.m[strings.ToLower(r)]; ok {
		return s
	}
	return poller.Snapshot{Repo: r, Data: poller.EmptyData(), Stale: true}
}
func (f *fSnaps) MarkViewed(r string) { f.viewed = append(f.viewed, r) }
func (f *fSnaps) Watched() []string   { return nil }

type fProducts struct {
	ps   []products.Product
	prds []products.PRD
}

func (f fProducts) Products() []products.Product { return f.ps }
func (f fProducts) Repos() []products.Repo       { return nil }
func (f fProducts) PRDs(string) ([]products.PRD, error) {
	return f.prds, nil
}

type fGrinds []inbox.GrindStatus

func (f fGrinds) Index() []inbox.GrindStatus { return f }

type fReleases struct {
	rel  []inbox.Release
	repo []inbox.ReleaseRepo
}

func (f fReleases) List(string) []inbox.Release      { return f.rel }
func (f fReleases) Repos(string) []inbox.ReleaseRepo { return f.repo }

type fDisp struct{ coords []inbox.Coordinator }

func (f fDisp) List() []inbox.Dispatch            { return nil }
func (f fDisp) Owned(string, int, int) bool       { return false }
func (f fDisp) Coordinators() []inbox.Coordinator { return f.coords }

type fGH struct{}

func (fGH) Get(context.Context) gh.Auth { return gh.Auth{OK: true, Login: "x"} }

type fBlub struct{}

func (fBlub) Status() blubird.Status { return blubird.Status{Installed: true, Version: "1.0"} }

func fresh(repo string, d poller.Data) poller.Snapshot {
	t := nowT.Add(-time.Minute)
	return poller.Snapshot{Repo: repo, Data: d, FetchedAt: &t}
}

func ptr[T any](v T) *T { return &v }

type fx struct {
	svc   *Service
	snaps *fSnaps
	sess  *fSess
}

func newFx(t *testing.T) *fx {
	t.Helper()
	docs := "acme/docs"
	api := "acme/api"
	prod := products.Product{DocsRepo: docs, Name: "acme", Repos: []products.ProductRepo{{Repo: api, Cloned: true}, {Repo: "acme/web", Cloned: false}}}
	epic := poller.Issue{N: 941, Title: "Epic: Courier cache", State: "OPEN", Labels: []string{"epic", "prd-courier"},
		SubIssues: []poller.Ref{{Repo: api, N: 10}, {Repo: api, N: 11}}, ClosedSubs: []poller.ClosedSub{}, BlockedBy: []poller.Blocker{}, PRs: []poller.PR{}}
	docsData := poller.Data{Issues: []poller.Issue{epic}, Merged: []poller.Merged{}, OpenPRs: []poller.OpenPR{}, ClosedEpics: []poller.ClosedEpic{}}
	mk := func(n int, title string, labels []string, status string) poller.Issue {
		return poller.Issue{N: n, Title: title, State: "OPEN", Labels: labels, Status: status, Parent: &poller.Ref{Repo: docs, N: 941},
			SubIssues: []poller.Ref{}, ClosedSubs: []poller.ClosedSub{}, BlockedBy: []poller.Blocker{}, PRs: []poller.PR{}}
	}
	apiData := poller.Data{
		Issues: []poller.Issue{
			mk(10, "Cache rates", []string{"refined"}, poller.StatusReady),
			mk(11, "Invalidate", nil, poller.StatusBacklog),
			func() poller.Issue {
				i := mk(12, "CSV drops VAT", []string{"bug"}, poller.StatusBacklog)
				i.Parent = nil
				return i
			}(),
			func() poller.Issue {
				i := mk(13, "Blocked work", []string{"refined"}, poller.StatusBacklog)
				i.Parent = nil
				i.BlockedBy = []poller.Blocker{{Ref: poller.Ref{Repo: api, N: 10}, State: "OPEN"}}
				return i
			}(),
			func() poller.Issue {
				i := mk(14, "Has a PR", []string{"refined"}, poller.StatusInReview)
				i.Parent = nil
				return i
			}(),
			func() poller.Issue {
				i := mk(15, "Draft work", []string{"refined"}, poller.StatusInReview)
				i.Parent = nil
				return i
			}(),
		},
		OpenPRs: []poller.OpenPR{
			{N: 50, Title: "Has a PR", URL: "https://github.com/acme/api/pull/50", Refs: []int{14}, CI: "success", ThreadsOpen: 2},
			{N: 51, Title: "Draft work", URL: "https://github.com/acme/api/pull/51", Refs: []int{15}, Draft: true, CI: "pending"},
			{N: 52, Title: "Release PR", URL: "https://github.com/acme/api/pull/52", CI: "success"},
		},
		Merged: []poller.Merged{}, ClosedEpics: []poller.ClosedEpic{},
	}
	snaps := &fSnaps{m: map[string]poller.Snapshot{
		docs: fresh(docs, docsData), api: fresh(api, apiData),
	}}
	sess := &fSess{}
	s := New(Deps{
		Inbox:     nil,
		Sessions:  sess,
		Snapshots: snaps,
		Products: fProducts{ps: []products.Product{prod}, prds: []products.PRD{
			{Product: docs, Slug: "draft", Title: "Draft PRD", Status: "Draft", Path: "docs/prds/draft.md", Label: "prd-draft"},
			{Product: docs, Slug: "rev", Title: "In review PRD", Status: "In review", Path: "docs/prds/m/rev.md", Label: "prd-rev", Module: ptr("m")},
			{Product: docs, Slug: "appr", Title: "Approved PRD", Status: "Approved", Path: "docs/prds/appr.md", Label: "prd-appr"},
			{Product: docs, Slug: "courier", Title: "Courier cache", Status: "Approved", Path: "docs/prds/courier.md", Label: "prd-courier"},
			{Product: docs, Slug: "done", Title: "Old", Status: "Done", Path: "docs/prds/done.md", Label: "prd-done"},
		}},
		Prompts: steps,
		Now:     now,
	})
	return &fx{svc: s, snaps: snaps, sess: sess}
}

func cardsOf(r River, stage string) []Card {
	for _, s := range r.Stages {
		if s.ID == stage {
			return s.Cards
		}
	}
	return nil
}

func ids(cs []Card) string {
	var out []string
	for _, c := range cs {
		out = append(out, c.ID)
	}
	return strings.Join(out, ",")
}

func TestRiverStagesFromSnapshots(t *testing.T) {
	f := newFx(t)
	// a release in flight takes the release PR out of review
	f.svc.d.Releases = fReleases{
		rel:  []inbox.Release{{ID: "r-1", Repo: "acme/api", Head: "staging", Base: "master", Stage: "grind", PR: ptr(52), PRURL: ptr("https://github.com/acme/api/pull/52")}},
		repo: []inbox.ReleaseRepo{{Repo: "acme/api", Head: "staging", Base: "master", Ahead: ptr(3), Open: ptr("r-1")}, {Repo: "acme/web", Head: "staging", Base: "master", Ahead: ptr(2)}, {Repo: "acme/x", Ahead: ptr(0)}},
	}
	r := f.svc.River(context.Background(), "ACME/docs", "")
	if r.Product != "acme/docs" || len(r.Stages) != 7 {
		t.Fatalf("river %+v", r)
	}
	var order []string
	for _, s := range r.Stages {
		order = append(order, s.ID)
	}
	if strings.Join(order, ",") != "prd,tasks,refine,implement,review,release,notify" {
		t.Fatalf("stage order %v", order)
	}
	if got := ids(cardsOf(r, "prd")); got != "prd:draft,prd:rev,prd:appr" {
		t.Errorf("prd cards %s", got)
	}
	if got := ids(cardsOf(r, "tasks")); got != "epic:acme/docs#941" {
		t.Errorf("tasks cards %s", got)
	}
	if c := cardsOf(r, "tasks")[0]; !strings.Contains(c.Actions[0].Label, "Refine all 1") || c.Meta != "epic #941 · 2 issues" {
		t.Errorf("epic card %+v", c)
	}
	if got := ids(cardsOf(r, "refine")); got != "issue:acme/api#11,issue:acme/api#12" {
		t.Errorf("refine cards %s", got)
	}
	if got := ids(cardsOf(r, "implement")); got != "issue:acme/api#10,issue:acme/api#13,issue:acme/api#15" {
		t.Errorf("implement cards %s", got)
	}
	if got := ids(cardsOf(r, "review")); got != "pr:acme/api#50" {
		t.Errorf("review cards %s", got)
	}
	rv := cardsOf(r, "review")[0]
	hasKey := map[string]bool{}
	for _, a := range rv.Actions {
		hasKey[a.Key] = true
	}
	if !hasKey["x"] || !hasKey["g"] || !strings.Contains(rv.Meta, "2 open threads") {
		t.Errorf("review card %+v", rv)
	}
	if got := ids(cardsOf(r, "release")); got != "release:r-1,repo:acme/web" {
		t.Errorf("release cards %s", got)
	}
	if got := ids(cardsOf(r, "notify")); got != "" {
		t.Errorf("notify cards %s", got)
	}
	// blocked card says why; bug card offers reproduce
	for _, c := range cardsOf(r, "implement") {
		if c.ID == "issue:acme/api#13" && (c.Tag != "blocked" || c.Meta != "waiting on #10") {
			t.Errorf("blocked card %+v", c)
		}
	}
	for _, c := range cardsOf(r, "refine") {
		if c.ID == "issue:acme/api#12" && (c.Tag != "bug" || len(c.Actions) < 3) {
			t.Errorf("bug card %+v", c)
		}
	}
	// the board was marked viewed for every product repo; nothing stale
	if len(f.snaps.viewed) != 3 {
		t.Errorf("viewed %v", f.snaps.viewed)
	}
	if strings.Join(r.Stale, ",") != "acme/web" || r.FetchedAt == nil {
		t.Errorf("stale %v fetched %v", r.Stale, r.FetchedAt)
	}
	// every action is a known route
	for _, st := range r.Stages {
		for _, c := range st.Cards {
			for _, a := range c.Actions {
				if a.Open == "" && !inboxtest.Known(a.Method, a.Path) {
					t.Errorf("%s: unknown route %s %s", c.ID, a.Method, a.Path)
				}
			}
		}
	}
}

func TestRiverNeedMatchesInboxAndAsk(t *testing.T) {
	f := newFx(t)
	cost := 1.5
	q := sessions.Record{ID: "20261112T090000000001Z-aaaaaaaa", Step: "implement-issue", Command: "/blubird:implement-issue 10", Repo: "acme/api",
		Status: sessions.StWaiting, StartedAt: "2026-11-12T09:00:00Z", Cost: &cost,
		Link:            &sessions.Link{Owner: "acme", Repo: "api", Issue: 10},
		PendingQuestion: &sessions.Round{ID: "r1", Status: "pending", Questions: []sessions.Question{{Question: "Nullable?"}}}}
	live := sessions.Record{ID: "20261112T095000000001Z-bbbbbbbb", Step: "refine-issues", Command: "/blubird:refine-issues 11", Repo: "acme/api",
		Status: sessions.StRunning, StartedAt: "2026-11-12T09:50:00Z", Link: &sessions.Link{Owner: "acme", Repo: "api", Issue: 11}}
	failed := sessions.Record{ID: "20261112T080000000001Z-cccccccc", Step: "verifier-locally", Command: "/blubird:verifier-locally 9", Repo: "acme/api",
		Status: sessions.StFailed, StartedAt: "2026-11-12T08:00:00Z", EndedAt: "2026-11-12T08:10:00Z", Error: "phpstan failed\nline2"}
	other := sessions.Record{ID: "20261112T070000000001Z-dddddddd", Step: "implement-issue", Command: "x", Repo: "other/repo", Status: sessions.StRunning, StartedAt: "2026-11-12T07:00:00Z"}
	f.sess.recs = []sessions.Record{q, live, failed, other}
	f.svc.d.Inbox = inbox.New(inbox.Deps{Sessions: f.sess, Snapshots: f.snaps, Products: f.svc.d.Products, Now: now})

	r := f.svc.River(context.Background(), "acme/docs", "")
	by := map[string]Card{}
	for _, st := range r.Stages {
		for _, c := range st.Cards {
			by[c.ID] = c
		}
	}
	c10 := by["issue:acme/api#10"]
	if !c10.Need || c10.NeedKind == nil || *c10.NeedKind != "Question" || c10.Ask == nil || c10.Ask.SessionID != q.ID || !c10.Live {
		t.Fatalf("question card %+v", c10)
	}
	if c10.Skill != "blubird:implement-issue" {
		t.Errorf("skill %q", c10.Skill)
	}
	if cardsOf(r, "implement")[0].ID != "issue:acme/api#10" {
		t.Errorf("need card should sort first: %s", ids(cardsOf(r, "implement")))
	}
	c11 := by["issue:acme/api#11"]
	if c11.Need || !c11.Live {
		t.Errorf("live refine card %+v", c11)
	}
	fc, ok := by["session:"+failed.ID]
	if !ok || !fc.Need || *fc.NeedKind != "Failed" || fc.Stage != "implement" || fc.Log[len(fc.Log)-1] != "phpstan failed" {
		t.Fatalf("failed session card %+v", fc)
	}
	if _, ok := by["session:"+other.ID]; ok {
		t.Error("session of another product on the board")
	}
	// need on cards == non-wait inbox items that have a card
	list := f.svc.d.Inbox.Build(context.Background(), "acme/docs", "")
	for _, it := range list.Items {
		if it.Type == inbox.TQuestion && !by["issue:acme/api#10"].Need {
			t.Error("inbox question without a needy card")
		}
	}
	// the question item's own actions come first on the card
	if c10.Actions[0].Key != "o" || c10.Actions[0].Open == "" {
		t.Errorf("card actions %+v", c10.Actions)
	}
	if st := r.Stages[3]; !st.Hot {
		t.Error("implement stage should be hot")
	}
}

func TestRiverNotifyAndPRDApproval(t *testing.T) {
	f := newFx(t)
	note := "@here release"
	f.svc.d.Releases = fReleases{rel: []inbox.Release{
		{ID: "r-2", Repo: "acme/api", Stage: "notify", PR: ptr(60), Note: &note, UpdatedAt: "2026-11-12T09:00:00Z"},
		{ID: "r-3", Repo: "acme/api", Stage: "notify", PR: ptr(61)},
	}}
	f.svc.d.NoteChannel = func() string { return "dc-supports" }
	f.svc.d.Inbox = inbox.New(inbox.Deps{Snapshots: f.snaps, Products: f.svc.d.Products, Releases: f.svc.d.Releases, Now: now})
	r := f.svc.River(context.Background(), "", "")
	for _, st := range r.Stages {
		for _, c := range st.Cards {
			if c.Log == nil || c.Actions == nil {
				t.Errorf("card %s: log and actions must be [] not null", c.ID)
			}
		}
	}
	notify := cardsOf(r, "notify")
	if len(notify) != 2 || notify[0].ID != "release:r-2" || !notify[0].Need || *notify[0].NeedKind != "Release" || notify[0].Note == nil || *notify[0].Note != note {
		t.Fatalf("notify cards %+v", notify)
	}
	if notify[0].Actions[0].Label != "Post to #dc-supports" || !notify[0].Actions[0].Clears {
		t.Errorf("post action %+v", notify[0].Actions[0])
	}
	if notify[1].Need || notify[1].Tag != "drafting" {
		t.Errorf("draft card %+v", notify[1])
	}
	var rev Card
	for _, c := range cardsOf(r, "prd") {
		if c.ID == "prd:rev" {
			rev = c
		}
	}
	if !rev.Need || *rev.NeedKind != "Approval" || rev.Actions[0].Label != "Approve + create epic" {
		t.Errorf("prd card %+v", rev)
	}
	n := 0
	for _, a := range rev.Actions {
		if a.Label == "Approve + create epic" {
			n++
		}
	}
	if n != 1 {
		t.Errorf("approve action duplicated %d times", n)
	}
}

func TestRiverGrindAndCoordinator(t *testing.T) {
	f := newFx(t)
	f.svc.d.Grinds = fGrinds{{Repo: "acme/api", PR: 50, State: "running", Rounds: 2}}
	sid := "20261112T090000000001Z-aaaaaaaa"
	f.svc.d.Dispatch = fDisp{coords: []inbox.Coordinator{
		{Run: "run1", Repo: "acme/api", Source: "label:payments", Live: true, Session: &sid, Events: []string{"a", "b"}},
		{Run: "old", Repo: "acme/api", Live: false},
		{Run: "elsewhere", Repo: "x/y", Live: true},
	}}
	r := f.svc.River(context.Background(), "acme/docs", "")
	rv := cardsOf(r, "review")[0]
	if !rv.Live || rv.Tag != "grind r2" || rv.Skill != "pr-grind" {
		t.Errorf("grind card %+v", rv)
	}
	for _, a := range rv.Actions {
		if a.Key == "g" {
			t.Error("a running grind offers no Grind action")
		}
	}
	var co *Card
	for _, c := range cardsOf(r, "implement") {
		if c.ID == "coord:run1" {
			cc := c
			co = &cc
		}
		if strings.HasPrefix(c.ID, "coord:") && c.ID != "coord:run1" {
			t.Errorf("unexpected coordinator card %s", c.ID)
		}
	}
	if co == nil || !co.Live || co.Log[len(co.Log)-1] != "b" || co.Actions[len(co.Actions)-1].Path != "/api/coordinators/run1/stop" {
		t.Fatalf("coord card %+v", co)
	}
}

func TestPRDsJoinEpic(t *testing.T) {
	f := newFx(t)
	prds, err := f.svc.PRDs("acme/docs")
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range prds {
		if p.Slug == "courier" && (p.Epic == nil || *p.Epic != "acme/docs#941") {
			t.Errorf("courier epic %v", p.Epic)
		}
		if p.Slug == "draft" && p.Epic != nil {
			t.Errorf("draft epic %v", p.Epic)
		}
	}
}

func TestOps(t *testing.T) {
	f := newFx(t)
	c := 1.2
	f.sess.recs = []sessions.Record{
		{ID: "20261110T090000000001Z-aaaaaaaa", Step: "agentic-onboard", Repo: "acme/api", Status: sessions.StDone, StartedAt: "2026-11-10T09:00:00Z", Cost: &c},
		{ID: "20261111T090000000001Z-bbbbbbbb", Step: "map-prds", Repo: "acme/docs", Status: sessions.StDone, StartedAt: "2026-11-11T09:00:00Z"},
	}
	o := f.svc.Ops(context.Background(), "acme/docs", "")
	var got []string
	rows := map[string]OpsRow{}
	for _, r := range o.Rows {
		got = append(got, r.Step)
		rows[r.Step] = r
	}
	if strings.Join(got, ",") != "map-prds,agentic-onboard,skill-feedback" {
		t.Fatalf("rows %v", got)
	}
	ao := rows["agentic-onboard"]
	if ao.Scope != "each repo" || len(ao.Targets) != 3 || ao.Summary != "1/3 repos ran" {
		t.Fatalf("onboard %+v", ao)
	}
	if ao.Targets[1].Note != "done 10 Nov · $1.20" || ao.Targets[2].Note != "not cloned" {
		t.Errorf("notes %+v", ao.Targets)
	}
	// never-run docs repo comes first, not the cloned-and-run api repo or the missing clone
	if b := ao.Actions[0].Body.(map[string]any); b["repo"] != "acme/docs" || ao.Actions[0].Key != "r" {
		t.Errorf("next target %+v", ao.Actions[0])
	}
	if rows["map-prds"].Scope != "docs repo" || rows["map-prds"].Summary != "last run: done 11 Nov" {
		t.Errorf("map-prds %+v", rows["map-prds"])
	}
	if rows["skill-feedback"].Scope != "any repo" || rows["skill-feedback"].Summary != "never run" || len(rows["skill-feedback"].Targets) != 1 {
		t.Errorf("skill-feedback %+v", rows["skill-feedback"])
	}
	for _, r := range o.Rows {
		for _, a := range r.Actions {
			if !inboxtest.Known(a.Method, a.Path) {
				t.Errorf("unknown route %s", a.Path)
			}
		}
	}
}

func TestMe(t *testing.T) {
	f := newFx(t)
	f.sess.recs = []sessions.Record{
		{ID: "a", Step: "day-end-reconcile", Status: sessions.StDone, StartedAt: "2026-11-12T08:00:00Z"},
		{ID: "b", Step: "day-end-reconcile", Status: sessions.StDone, StartedAt: "2026-11-10T08:00:00Z"},
		{ID: "c", Step: "day-end-reconcile", Status: sessions.StFailed, StartedAt: "2026-11-11T08:00:00Z"},
		{ID: "d", Step: "weekly-review", Status: sessions.StRunning, StartedAt: "2026-11-09T08:00:00Z"},
	}
	m := f.svc.Me(context.Background())
	if m.DayEnd.Date != "2026-11-12" || !m.DayEnd.Reconciled || m.DayEnd.Last.ID != "a" {
		t.Errorf("day end %+v", m.DayEnd)
	}
	// Nov 2026: weekdays 2-6, 9-11 before the 12th = 8; done on the 10th = 1 -> 7 missing
	if m.DayEnd.MissingDays != 7 {
		t.Errorf("missing %d", m.DayEnd.MissingDays)
	}
	if m.Weekly.Week != 46 || !m.Weekly.Drafted || m.Weekly.Last.ID != "d" {
		t.Errorf("weekly %+v", m.Weekly)
	}
	if m.Cost.MonthCost != 4.5 || len(m.Actions) != 2 || m.Usage == nil {
		t.Errorf("me %+v", m)
	}
	for _, a := range m.Actions {
		if !inboxtest.Known(a.Method, a.Path) {
			t.Errorf("unknown %s", a.Path)
		}
	}
	// a new week and no sessions
	f.sess.recs = nil
	nowT = time.Date(2026, 11, 16, 10, 0, 0, 0, time.UTC)
	defer func() { nowT = time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC) }()
	m = f.svc.Me(context.Background())
	if m.DayEnd.Reconciled || m.Weekly.Drafted || m.Weekly.Week != 47 || m.DayEnd.Last != nil {
		t.Errorf("empty me %+v", m)
	}
}

type fUsage map[string]claude.AccountUsage

func (f fUsage) Snapshot() map[string]claude.AccountUsage { return f }

type fAccts []settings.Account

func (f fAccts) Accounts() []settings.Account { return f }

type fBudget struct{ gh.RateLimit }

func (f fBudget) Budget() gh.RateLimit { return f.RateLimit }

type fAway struct{ a inbox.Away }

func (f fAway) Public() inbox.Away { return f.a }

func TestStatus(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SETU_HOME", dir)
	h, err := home.Open()
	if err != nil {
		t.Fatal(err)
	}
	f := newFx(t)
	f.sess.limits = map[string]sessions.Limit{"cc": {LimitedUntil: 99}}
	f.svc.d.Home = h
	f.svc.d.Version, f.svc.d.BootID = "1.2.3", func() string { return "boot" }
	f.svc.d.GH, f.svc.d.Blubird = fGH{}, fBlub{}
	f.svc.d.Accounts = fAccts{{Label: "claude", Cmd: "claude", Builtin: true}, {Label: "work", Cmd: "cc"}}
	f.svc.d.Usage = fUsage{"cc": {Label: "work", Cmd: "cc"}, "claude": {Label: "claude", Cmd: "claude"}, "gone": {Label: "gone", Cmd: "gone"}}
	f.svc.d.Away = fAway{inbox.Away{Active: true}}
	f.svc.d.Poller = fBudget{gh.RateLimit{Remaining: -1}}
	if f.svc.UIPresent() {
		t.Fatal("no UI yet")
	}
	st := f.svc.Status(context.Background())
	if !f.svc.UIPresent() {
		t.Fatal("status marks the UI present")
	}
	if st.Version != "1.2.3" || st.BootID != "boot" || st.Migrated || !st.Blubird.Installed || st.Blubird.Skills == nil {
		t.Errorf("status %+v", st)
	}
	if len(st.Usage) != 3 || st.Usage[0].Cmd != "claude" || st.Usage[1].Cmd != "cc" || st.Usage[1].Limit.LimitedUntil != 99 || st.Usage[2].Cmd != "gone" {
		t.Errorf("usage %+v", st.Usage)
	}
	if st.Poller.Remaining != nil || st.Poller.ResetAt != nil {
		t.Errorf("budget unknown must be null: %+v", st.Poller)
	}
	if err := os.WriteFile(filepath.Join(dir, ".migrated"), nil, 0o644); err != nil {
		t.Fatal(err)
	}
	reset := nowT.Add(time.Hour)
	f.svc.d.Poller = fBudget{gh.RateLimit{Remaining: 4000, ResetAt: reset}}
	st = f.svc.Status(context.Background())
	if !st.Migrated || st.Poller.Remaining == nil || *st.Poller.Remaining != 4000 || *st.Poller.ResetAt != "2026-11-12T11:00:00Z" {
		t.Errorf("status %+v", st)
	}
	nowT = nowT.Add(3 * time.Minute)
	defer func() { nowT = time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC) }()
	if f.svc.UIPresent() {
		t.Error("presence expires after 120 s")
	}
}

func TestRoutes(t *testing.T) {
	f := newFx(t)
	mux := http.NewServeMux()
	for _, r := range Routes(f.svc) {
		mux.Handle(r.Pattern, r.Handler)
	}
	get := func(path string) (int, map[string]any) {
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, httptest.NewRequest("GET", path, nil))
		var m map[string]any
		_ = json.Unmarshal(w.Body.Bytes(), &m)
		return w.Code, m
	}
	if code, m := get("/api/river?product=acme/docs"); code != 200 || len(m["stages"].([]any)) != 7 {
		t.Errorf("river %d %v", code, m)
	}
	if code, m := get("/api/river?product=nope/none"); code != 400 || m["error"] == nil {
		t.Errorf("unknown product %d %v", code, m)
	}
	if code, m := get("/api/river"); code != 200 || m["product"] != "acme/docs" {
		t.Errorf("default product %d %v", code, m)
	}
	if code, _ := get("/api/ops?product=nope/none"); code != 400 {
		t.Errorf("ops unknown %d", code)
	}
	if code, m := get("/api/ops?product=acme/docs"); code != 200 || m["rows"] == nil {
		t.Errorf("ops %d", code)
	}
	if code, m := get("/api/me"); code != 200 || m["day_end"] == nil {
		t.Errorf("me %d", code)
	}
	if code, m := get("/api/status"); code != 200 || m["usage"] == nil || m["poller"] == nil {
		t.Errorf("status %d %v", code, m)
	}
}

func TestOpsStandaloneRepo(t *testing.T) {
	f := newFx(t)
	o := f.svc.Ops(context.Background(), "acme/docs", "solo/app")
	if o.Product != "" {
		t.Errorf("product %q", o.Product)
	}
	for _, r := range o.Rows {
		switch r.Scope {
		case "docs repo":
			if len(r.Targets) != 0 || len(r.Actions) != 0 || r.Summary != "needs a product" {
				t.Errorf("%s %+v", r.Step, r)
			}
		default:
			if len(r.Targets) != 1 || r.Targets[0].Repo != "solo/app" || len(r.Actions) != 1 {
				t.Fatalf("%s %+v", r.Step, r)
			}
			if b := r.Actions[0].Body.(map[string]any); b["repo"] != "solo/app" || b["product"] != nil {
				t.Errorf("%s body %v", r.Step, b)
			}
		}
	}
	// a repo of a product shows that product
	if o := f.svc.Ops(context.Background(), "", "acme/api"); o.Product != "acme/docs" {
		t.Errorf("product of acme/api %q", o.Product)
	}
}

func TestRiverStandaloneRepo(t *testing.T) {
	f := newFx(t)
	f.svc.d.Releases = fReleases{rel: []inbox.Release{
		{ID: "r-solo", Repo: "solo/app", Stage: "cut"},
		{ID: "r-api", Repo: "acme/api", Stage: "cut"},
	}}
	f.svc.d.Dispatch = fDisp{coords: []inbox.Coordinator{
		{Run: "solo", Repo: "solo/app", Source: "label:x", Live: true},
		{Run: "api", Repo: "acme/api", Source: "label:y", Live: true},
	}}
	r := f.svc.River(context.Background(), "acme/docs", "solo/app")
	if r.Product != "" {
		t.Errorf("product %q", r.Product)
	}
	if prds := cardsOf(r, "prd"); len(prds) != 0 {
		t.Errorf("a standalone repo has no PRDs: %+v", prds)
	}
	if rel := cardsOf(r, "release"); len(rel) != 1 || rel[0].ID != "release:r-solo" {
		t.Errorf("release cards %+v", rel)
	}
	if im := cardsOf(r, "implement"); len(im) != 1 || im[0].ID != "coord:solo" {
		t.Errorf("implement cards %+v", im)
	}
	// a repo of a product shows that product
	if r := f.svc.River(context.Background(), "", "acme/api"); r.Product != "acme/docs" {
		t.Errorf("product of acme/api %q", r.Product)
	}
}
