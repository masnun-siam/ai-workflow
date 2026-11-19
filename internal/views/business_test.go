package views

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"testing"

	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/inbox"
	"github.com/masnun-siam/setu/internal/poller"
	"github.com/masnun-siam/setu/internal/products"
)

type fBusiness struct {
	docs []products.BusinessDoc
	gate products.BusinessGate
}

func (f fBusiness) BusinessDocs(string) ([]products.BusinessDoc, error) { return f.docs, nil }
func (f fBusiness) BusinessGate(string) products.BusinessGate           { return f.gate }

type fDispList struct {
	fDisp
	list []inbox.Dispatch
}

func (f fDispList) List() []inbox.Dispatch { return f.list }

func bdoc(path string, prds ...string) products.BusinessDoc {
	if prds == nil {
		prds = []string{}
	}
	return products.BusinessDoc{Path: path, PRDs: prds}
}

func TestMatchBusiness(t *testing.T) {
	docs := []products.BusinessDoc{
		bdoc("docs/business/auth/a.md", "docs/prds/auth/login.md"),
		bdoc("docs/business/auth/login.md", "docs/prds/auth/login.md"),
		bdoc("docs/business/billing/b.md", "docs/prds/auth/login.md", "docs/prds/x.md"),
		bdoc("docs/business/other.md"),
		bdoc("docs/business/flat.md"),
	}
	cases := map[string][]string{
		"docs/prds/auth/login.md": {"docs/business/auth/login.md", "docs/business/auth/a.md", "docs/business/billing/b.md"},
		"docs/prds/x.md":          {"docs/business/billing/b.md"},
		"docs/prds/flat.md":       {"docs/business/flat.md"},
		"docs/prds/none.md":       {},
	}
	for prd, want := range cases {
		if got := matchBusiness(prd, docs); !reflect.DeepEqual(got, want) {
			t.Errorf("%s: %v want %v", prd, got, want)
		}
	}
	if got := matchBusiness("docs/prds/x.md", nil); got == nil || len(got) != 0 {
		t.Errorf("nil docs %v", got)
	}
}

func TestValidationModule(t *testing.T) {
	for in, want := range map[string]string{
		"Business validation: Auth":     "auth",
		"business VALIDATION:  Billing": "billing",
		"Business validation:":          "other",
		"Business validation":           "other",
		"Something else":                "other",
	} {
		if got := validationModule(in); got != want {
			t.Errorf("%q: %q want %q", in, got, want)
		}
	}
}

// addValidationEpics puts business validation epics and their children in the fixture's snapshots.
func addValidationEpics(f *fx) {
	mk := func(n int, title string, labels []string, parent *poller.Ref, state string) poller.Issue {
		return poller.Issue{N: n, Title: title, State: state, Labels: labels, Parent: parent,
			SubIssues: []poller.Ref{}, ClosedSubs: []poller.ClosedSub{}, BlockedBy: []poller.Blocker{}, PRs: []poller.PR{}}
	}
	docs := f.snaps.m["acme/docs"]
	auth := mk(900, "Business validation: Auth", []string{"epic", "business-validation"}, nil, "OPEN")
	auth.SubIssues = []poller.Ref{{Repo: "acme/api", N: 20}}
	docs.Data.Issues = append(docs.Data.Issues,
		auth,
		mk(21, "Login drifted", nil, &poller.Ref{Repo: "acme/docs", N: 900}, "OPEN"),
		mk(901, "Business validation", []string{"epic", "business-validation"}, nil, "OPEN"),
		mk(902, "Business validation: Closed", []string{"epic", "business-validation"}, nil, "CLOSED"),
		mk(903, "Business validation: Half", []string{"business-validation"}, nil, "OPEN"),
		mk(904, "Business validation: Half", []string{"epic"}, nil, "OPEN"),
	)
	f.snaps.m["acme/docs"] = docs
	api := f.snaps.m["acme/api"]
	api.Data.Issues = append(api.Data.Issues, mk(20, "Signup rule", []string{"refined"}, nil, "OPEN"))
	f.snaps.m["acme/api"] = api
}

func TestBusinessView(t *testing.T) {
	f := newFx(t)
	addValidationEpics(f)
	reason := "not checked yet"
	f.svc.d.Business = fBusiness{docs: []products.BusinessDoc{bdoc("docs/business/auth/login.md")},
		gate: products.BusinessGate{State: "unavailable", Reason: &reason, Failures: []string{}}}

	v, err := f.svc.Business(context.Background(), "ACME/docs")
	if err != nil {
		t.Fatal(err)
	}
	if len(v.Docs) != 1 || v.Gate.State != "unavailable" || *v.Gate.Reason != "not checked yet" {
		t.Fatalf("%+v", v)
	}
	if len(v.Epics) != 2 {
		t.Fatalf("epics %+v", v.Epics)
	}
	a, o := v.Epics[0], v.Epics[1]
	if a.Module != "auth" || a.N != 900 || a.Repo != "acme/docs" || a.URL != "https://github.com/acme/docs/issues/900" || a.Title != "Business validation: Auth" {
		t.Fatalf("auth epic %+v", a)
	}
	if len(a.Issues) != 2 || a.Issues[0].Key != "acme/api#20" || a.Issues[1].Key != "acme/docs#21" {
		t.Fatalf("children %+v", a.Issues)
	}
	// the same state and actions a feature issue gets
	if a.Issues[0].State != "ready" || labels(a.Issues[0].Actions) != "Start" || a.Issues[1].State != "unrefined" || labels(a.Issues[1].Actions) != "Refine" {
		t.Errorf("states %+v", a.Issues)
	}
	if labels(a.Actions) != "Run epic" || !a.Actions[0].Primary || a.Actions[0].Open != "#/dispatches?new=acme%2Fdocs%23900" {
		t.Errorf("actions %+v", a.Actions)
	}
	if o.Module != "other" || o.N != 901 || o.Issues == nil || len(o.Issues) != 0 || o.Actions == nil || len(o.Actions) != 0 {
		t.Errorf("other epic %+v", o)
	}

	// a dispatch owning the epic swaps Run epic for Open dispatch
	epic := "acme/docs#900"
	f.svc.d.Dispatch = fDispList{list: []inbox.Dispatch{{ID: "d1", Epic: &epic, State: "running"}}}
	v, _ = f.svc.Business(context.Background(), "acme/docs")
	if labels(v.Epics[0].Actions) != "Open dispatch" {
		t.Errorf("dispatched %+v", v.Epics[0].Actions)
	}

	// never a Feature row, and never a change
	for _, ft := range f.svc.Features(context.Background(), "acme/docs").Features {
		if ft.Epic != nil && strings.HasSuffix(ft.Epic.Key, "#900") {
			t.Errorf("feature row for the validation epic: %+v", ft)
		}
	}
	for _, is := range f.svc.Changes(context.Background(), "").Issues {
		if is.N == 900 || is.N == 901 || is.N == 21 {
			t.Errorf("change for %s", is.Key)
		}
	}

	if _, err := f.svc.Business(context.Background(), "who/dis"); errs.KindOf(err) != errs.KNotFound {
		t.Fatalf("unknown product %v", err)
	}
}

func TestBusinessViewWithoutDeps(t *testing.T) {
	f := newFx(t)
	v, err := f.svc.Business(context.Background(), "acme/docs")
	if err != nil || v.Docs == nil || v.Epics == nil || v.Gate.Failures == nil || v.Gate.State != "unavailable" {
		t.Fatalf("%+v %v", v, err)
	}
	for _, ft := range f.svc.Features(context.Background(), "acme/docs").Features {
		if ft.Business == nil || len(ft.Business) != 0 {
			t.Errorf("%s business %v", ft.Slug, ft.Business)
		}
	}
}

func TestFeaturesBusiness(t *testing.T) {
	f := newFx(t)
	f.svc.d.Business = fBusiness{docs: []products.BusinessDoc{
		bdoc("docs/business/courier.md"),
		bdoc("docs/business/ops/cache.md", "docs/prds/courier.md"),
	}}
	l := f.svc.Features(context.Background(), "acme/docs")
	if got := featureBySlug(l, "courier").Business; !reflect.DeepEqual(got, []string{"docs/business/courier.md", "docs/business/ops/cache.md"}) {
		t.Errorf("courier %v", got)
	}
	if got := featureBySlug(l, "draft").Business; got == nil || len(got) != 0 {
		t.Errorf("draft %v", got)
	}
}

func TestBusinessRoute(t *testing.T) {
	f := newFx(t)
	f.svc.d.Business = fBusiness{docs: []products.BusinessDoc{}, gate: products.BusinessGate{State: "pass", Failures: []string{}}}
	mux := http.NewServeMux()
	for _, rt := range Routes(f.svc) {
		mux.Handle(rt.Pattern, rt.Handler)
	}
	get := func(path string) (int, map[string]any) {
		w := httptest.NewRecorder()
		mux.ServeHTTP(w, httptest.NewRequest("GET", path, nil))
		var m map[string]any
		json.Unmarshal(w.Body.Bytes(), &m)
		return w.Code, m
	}
	code, m := get("/api/products/acme/docs/business")
	if code != 200 || m["docs"] == nil || m["epics"] == nil || m["gate"].(map[string]any)["state"] != "pass" {
		t.Fatalf("%d %v", code, m)
	}
	if code, m := get("/api/products/who/dis/business"); code != 404 || m["error"] == nil {
		t.Fatalf("%d %v", code, m)
	}
}
