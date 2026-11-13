package views

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"github.com/masnun-siam/setu/internal/inbox"
	"github.com/masnun-siam/setu/internal/inbox/inboxtest"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/products"
	"github.com/masnun-siam/setu/internal/sessions"
)

func featureBySlug(l FeatureList, slug string) Feature {
	for _, f := range l.Features {
		if f.Slug == slug {
			return f
		}
	}
	return Feature{}
}

func labels(as []inbox.Action) string {
	var out []string
	for _, a := range as {
		out = append(out, a.Label)
	}
	return strings.Join(out, ",")
}

func TestFeaturesStagesAndNextSteps(t *testing.T) {
	f := newFx(t)
	l := f.svc.Features(context.Background(), "acme/docs")
	if l.Product != "acme/docs" || len(l.Features) != 5 {
		t.Fatalf("%+v", l)
	}
	cases := []struct{ slug, stage, bay, actions string }{
		{"draft", "draft", "go", "Start peer review,Approve without review,Read PRD"},
		{"rev", "review", "you", "Approve PRD,Start peer review,Read PRD"},
		{"appr", "approved", "go", "Create tasks,Read PRD"},
		{"courier", "tasks", "go", "Refine 1,Read PRD"},
		{"done", "shipped", "shipped", "Read PRD"},
	}
	for _, c := range cases {
		ft := featureBySlug(l, c.slug)
		if ft.Stage != c.stage || ft.Bay != c.bay || labels(ft.Actions) != c.actions {
			t.Errorf("%s: stage %s bay %s actions %s", c.slug, ft.Stage, ft.Bay, labels(ft.Actions))
		}
		if len(ft.Actions) > 1 && !ft.Actions[0].Primary {
			t.Errorf("%s: first action is not primary", c.slug)
		}
	}
	// bays sort you, go, running, shipped
	if l.Features[0].Bay != "you" || l.Features[len(l.Features)-1].Bay != "shipped" {
		t.Errorf("order %s .. %s", l.Features[0].Slug, l.Features[len(l.Features)-1].Slug)
	}
	c := featureBySlug(l, "courier")
	if c.Epic == nil || c.Epic.Key != "acme/docs#941" || c.Epic.Title != "Courier cache" || len(c.Issues) != 2 {
		t.Fatalf("epic %+v issues %+v", c.Epic, c.Issues)
	}
	if c.Issues[0].State != "ready" || labels(c.Issues[0].Actions) != "Start" || c.Issues[1].State != "unrefined" || labels(c.Issues[1].Actions) != "Refine" {
		t.Errorf("issues %+v", c.Issues)
	}

	// refine #11 and approve a PR for #10: building, the PR is mergeable, and #11 is ready to run
	api := f.snaps.m["acme/api"]
	for i := range api.Data.Issues {
		if api.Data.Issues[i].N == 11 {
			api.Data.Issues[i].Labels = []string{"refined"}
		}
	}
	api.Data.OpenPRs = append(api.Data.OpenPRs, poller.OpenPR{N: 60, URL: "https://github.com/acme/api/pull/60", Refs: []int{10}, CI: "success", Review: "approved",
		SHA: strings.Repeat("a", 40)})
	f.snaps.m["acme/api"] = api
	l = f.svc.Features(context.Background(), "acme/docs")
	c = featureBySlug(l, "courier")
	if c.Stage != "building" || c.Bay != "you" || c.Counts.Mergeable != 1 || c.Counts.Ready != 1 {
		t.Fatalf("building %+v", c)
	}
	if labels(c.Actions) != "Merge #60,Run epic,Read PRD" || !strings.Contains(c.Actions[1].Open, "#/dispatches?new=acme%2Fdocs%23941") {
		t.Errorf("actions %+v", c.Actions)
	}
	if c.Actions[0].Path != "/api/pulls/acme/api/60/merge" || c.Actions[0].Confirm == "" {
		t.Errorf("merge %+v", c.Actions[0])
	}
	for _, ft := range l.Features {
		for _, a := range append(append([]inbox.Action{}, ft.Actions...), issueActions(ft)...) {
			if a.Open == "" && !inboxtest.Known(a.Method, a.Path) {
				t.Errorf("%s: unknown route %s %s", ft.Slug, a.Method, a.Path)
			}
		}
	}
}

func issueActions(f Feature) []inbox.Action {
	var out []inbox.Action
	for _, i := range f.Issues {
		out = append(out, i.Actions...)
	}
	return out
}

func TestFeaturesPanelDecides(t *testing.T) {
	f := newFx(t)
	f.svc.d.Panels = fPanels{{ID: "p1", Artifact: "/docs/docs/prds/draft.md", State: "cap reached", Round: 3, MaxRounds: 3}}
	f.svc.d.Products = fProductsPath{f.svc.d.Products.(fProducts), "/docs"}
	d := featureBySlug(f.svc.Features(context.Background(), "acme/docs"), "draft")
	if d.Stage != "review" || d.Bay != "you" || labels(d.Actions) != "Run 2 more rounds,Approve anyway,Read PRD" {
		t.Fatalf("%+v", d)
	}
}

type fPanels []inbox.Panel

func (f fPanels) List() []inbox.Panel { return f }

// fProductsPath gives the docs product a checkout path so panel artifacts match.
type fProductsPath struct {
	fProducts
	path string
}

func (f fProductsPath) Products() []products.Product {
	ps := append([]products.Product{}, f.ps...)
	for i := range ps {
		ps[i].Path = f.path
	}
	return ps
}

type fProductsRepos struct {
	fProducts
	repos []products.Repo
}

func (f fProductsRepos) Repos() []products.Repo { return f.repos }

func TestChangesAreIssuesWithoutAnEpic(t *testing.T) {
	f := newFx(t)
	f.svc.d.Products = fProductsRepos{f.svc.d.Products.(fProducts), []products.Repo{{Slug: "acme/api"}, {Slug: "acme/docs"}, {Slug: "local/x"}}}
	c := f.svc.Changes(context.Background(), "")
	var got []string
	for _, i := range c.Issues {
		got = append(got, fmt.Sprintf("%d:%s", i.N, i.State))
	}
	if strings.Join(got, ",") != "12:unrefined,13:blocked,14:in_review,15:in_progress" {
		t.Fatalf("%v", got)
	}
	if one := f.svc.Changes(context.Background(), "acme/docs"); len(one.Issues) != 0 {
		t.Fatalf("docs repo has only the epic: %+v", one.Issues)
	}
}

func TestChangesPendingFilingRuns(t *testing.T) {
	f := newFx(t)
	f.svc.d.Products = fProductsRepos{f.svc.d.Products.(fProducts), []products.Repo{{Slug: "acme/api"}, {Slug: "acme/docs"}}}
	f.sess.recs = []sessions.Record{
		{ID: "bug-live", Step: "report-bug", Repo: "acme/api", Status: sessions.StWaiting, Command: "Report bug: CSV drops VAT", StartedAt: "2026-11-13T08:00:00Z"},
		{ID: "bug-done", Step: "report-bug", Repo: "acme/api", Status: sessions.StDone},
		{ID: "bug-failed", Step: "report-bug", Repo: "acme/api", Status: sessions.StFailed},
		{ID: "sc-live", Step: "small-change", Repo: "acme/api", Status: sessions.StRunning},
		{ID: "impl-live", Step: "implement-issue", Repo: "acme/api", Status: sessions.StRunning},
	}
	pendingIDs := func(repo string) string {
		var got []string
		for _, p := range f.svc.Changes(context.Background(), repo).Pending {
			got = append(got, p.ID)
		}
		return strings.Join(got, ",")
	}
	for repo, want := range map[string]string{"": "bug-live,sc-live", "acme/api": "bug-live,sc-live", "acme/docs": ""} {
		if got := pendingIDs(repo); got != want {
			t.Fatalf("Changes(%q).Pending = %q, want %q", repo, got, want)
		}
	}
	p := f.svc.Changes(context.Background(), "acme/api").Pending[0]
	if p.Status != "waiting" || p.Title != "Report bug: CSV drops VAT" || p.StartedAt != "2026-11-13T08:00:00Z" || p.Skill != "blubird:report-bug" {
		t.Fatalf("pending row: %+v", p)
	}
}
