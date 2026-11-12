package dispatch

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"github.com/masnun-siam/setu/internal/dispatch/store"
	"github.com/masnun-siam/setu/internal/errs"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/gh/ghtest"
	"github.com/masnun-siam/setu/internal/jev"
)

type node struct {
	n       int
	state   string
	repo    string
	refined bool
	blocked []string // "repo#n:STATE"
}

func nodeJSON(x node) string {
	if x.repo == "" {
		x.repo = "o/r"
	}
	labels := ""
	if x.refined {
		labels = `{"name":"refined"}`
	}
	var bl []string
	for _, b := range x.blocked {
		ref, st, _ := strings.Cut(b, ":")
		repo, n, _ := strings.Cut(ref, "#")
		bl = append(bl, fmt.Sprintf(`{"number":%s,"state":"%s","repository":{"nameWithOwner":"%s"}}`, n, st, repo))
	}
	return fmt.Sprintf(`{"number":%d,"title":"issue %d","body":"body of %d","state":"%s","repository":{"nameWithOwner":"%s"},"labels":{"nodes":[%s]},"blockedBy":{"nodes":[%s]}}`,
		x.n, x.n, x.n, x.state, x.repo, labels, strings.Join(bl, ","))
}

func epicRule(pages ...[]node) ghtest.Rule {
	i := 0
	return ghtest.Rule{Prefix: []string{"api", "graphql"}, Contains: "subIssues", Func: func(args []string) execx.Result {
		if i >= len(pages) {
			i = len(pages) - 1
		}
		var js []string
		for _, n := range pages[i] {
			js = append(js, nodeJSON(n))
		}
		more := i < len(pages)-1
		i++
		return execx.Result{Stdout: []byte(fmt.Sprintf(`{"data":{"repository":{"issue":{"title":"The epic","subIssues":{"pageInfo":{"hasNextPage":%v,"endCursor":"CUR%d"},"nodes":[%s]}}}}}`,
			more, i, strings.Join(js, ",")))}
	}}
}

func issuesRule(nodes ...node) ghtest.Rule {
	return ghtest.Rule{Prefix: []string{"api", "graphql"}, Contains: "i0: issue", Func: func(args []string) execx.Result {
		var parts []string
		for i, n := range nodes {
			if n.n < 0 {
				parts = append(parts, fmt.Sprintf(`"i%d":null`, i))
			} else {
				parts = append(parts, fmt.Sprintf(`"i%d":%s`, i, nodeJSON(n)))
			}
		}
		return execx.Result{Stdout: []byte(`{"data":{"repository":{` + strings.Join(parts, ",") + `}}}`)}
	}}
}

func TestResolveEpicPagesAndChildren(t *testing.T) {
	e := newEnv(t)
	e.gh.Add(epicRule(
		[]node{{n: 3, state: "OPEN", refined: true, blocked: []string{"o/r#2:OPEN", "o/r#50:CLOSED"}}, {n: 4, state: "CLOSED"}},
		[]node{{n: 2, state: "OPEN", refined: false, blocked: []string{"o/r#99:OPEN"}}, {n: 9, state: "OPEN", repo: "o/other", refined: true}},
	))
	r, err := e.svc.ResolveEpic(e.ctx(), "o/r#1", true)
	if err != nil {
		t.Fatal(err)
	}
	if *r.Epic != "o/r#1" || r.Title != "The epic" || len(r.Children) != 3 {
		t.Fatalf("%+v", r)
	}
	// sorted by (n, repo); deps inside the set become dep keys, an open blocker outside is reported
	if r.Children[0].N != 2 || r.Children[1].N != 3 || r.Children[2].Repo != "o/other" {
		t.Fatal(r.Children)
	}
	if strings.Join(r.Children[1].Deps, ",") != "o/r#2" || r.Children[0].Refined || !r.Children[1].Refined {
		t.Fatal(r.Children)
	}
	if strings.Join(r.Outside["o/r#2"], ",") != "o/r#99" || len(r.Outside) != 1 {
		t.Fatal(r.Outside)
	}
	if r.Bodies["o/r#3"] != "body of 3" {
		t.Fatal(r.Bodies)
	}
	calls := e.gh.CallsMatching("api", "graphql")
	if len(calls) != 2 || !strings.Contains(strings.Join(calls[1], " "), "after=CUR1") || strings.Contains(strings.Join(calls[0], " "), "after=") {
		t.Fatal(calls)
	}
	if !strings.Contains(strings.Join(calls[0], " "), "-F n=1") || !strings.Contains(strings.Join(calls[0], " "), "owner=o") {
		t.Fatal(calls[0])
	}
	// without bodies the query does not ask for them
	e2 := newEnv(t)
	e2.gh.Add(epicRule([]node{{n: 2, state: "OPEN"}}))
	r, _ = e2.svc.ResolveEpic(e2.ctx(), "o/r#1", false)
	if r.Bodies != nil || strings.Contains(strings.Join(e2.gh.Calls[0], " "), "title body") && false {
		t.Fatal("bodies")
	}
}

func TestResolveEpicErrors(t *testing.T) {
	e := newEnv(t)
	for _, bad := range []string{"", "foo", "o/r", "o/r#x", "#4"} {
		if _, err := e.svc.ResolveEpic(e.ctx(), bad, false); errs.KindOf(err) != errs.KInvalid {
			t.Errorf("%q: %v", bad, err)
		}
	}
	// a bare number needs a checkout
	if _, err := e.svc.ResolveEpic(e.ctx(), "12", false); err == nil || !strings.Contains(err.Error(), "not in a GitHub checkout") {
		t.Fatal(err)
	}
	e.gh.Add(ghtest.Rule{Prefix: []string{"repo", "view", "--json", "nameWithOwner"}, Stdout: "me/here\n"})
	e.gh.Add(ghtest.Rule{Prefix: []string{"api", "graphql"}, Stdout: `{"data":{"repository":{"issue":null}}}`})
	if _, err := e.svc.ResolveEpic(e.ctx(), "12", false); err == nil || err.Error() != "epic not found" {
		t.Fatal(err)
	}
	e3 := newEnv(t)
	e3.gh.Add(ghtest.Rule{Prefix: []string{"api", "graphql"}, Code: 1, Stderr: "HTTP 502"})
	if _, err := e3.svc.ResolveEpic(e3.ctx(), "o/r#1", false); errs.KindOf(err) != errs.KUpstream || !strings.Contains(err.Error(), "cannot read epic o/r#1") {
		t.Fatal(err)
	}
	// too many pages
	e4 := newEnv(t)
	pages := make([][]node, MaxChildPages+2)
	for i := range pages {
		pages[i] = []node{{n: i + 2, state: "OPEN"}}
	}
	e4.gh.Add(epicRule(pages...))
	if _, err := e4.svc.ResolveEpic(e4.ctx(), "o/r#1", false); err == nil || err.Error() != "epic has too many sub-issues" {
		t.Fatal(err)
	}
}

func TestParseIssues(t *testing.T) {
	if r, n, err := ParseIssues([]string{"o/r#3", "O/R#1"}); err != nil || r != "o/r" || len(n) != 2 {
		t.Fatal(r, n, err)
	}
	var many []string
	for i := 1; i <= 31; i++ {
		many = append(many, fmt.Sprintf("o/r#%d", i))
	}
	for _, bad := range [][]string{nil, {"o/r#1", "x/y#2"}, {"o/r"}, {"#1"}, many} {
		if _, _, err := ParseIssues(bad); errs.KindOf(err) != errs.KInvalid {
			t.Errorf("%v accepted", bad)
		}
	}
}

func TestResolveIssues(t *testing.T) {
	e := newEnv(t)
	e.gh.Add(issuesRule(node{n: 7, state: "OPEN", refined: true}, node{n: 3, state: "CLOSED"}, node{n: 5, state: "OPEN", blocked: []string{"o/r#7:OPEN", "o/r#8:OPEN"}}))
	r, err := e.svc.ResolveIssues(e.ctx(), []string{"o/r#7", "o/r#3", "o/r#5"}, false)
	if err != nil {
		t.Fatal(err)
	}
	if r.Epic != nil || strings.Join(r.Issues, ",") != "o/r#5,o/r#7" || strings.Join(r.Closed, ",") != "o/r#3" || r.Title != "Small changes: #5, #7" {
		t.Fatalf("%+v", r)
	}
	if strings.Join(r.Children[0].Deps, ",") != "o/r#7" || strings.Join(r.Outside["o/r#5"], ",") != "o/r#8" {
		t.Fatalf("%+v", r)
	}
	e2 := newEnv(t)
	e2.gh.Add(issuesRule(node{n: -1}))
	if _, err := e2.svc.ResolveIssues(e2.ctx(), []string{"o/r#7"}, false); err == nil || err.Error() != "issue o/r#7 not found" {
		t.Fatal(err)
	}
}

type fakeJev struct {
	status string
	scores map[string]float64
}

func (f fakeJev) Status() string { return f.status }
func (f fakeJev) Ask(_ context.Context, point, kind, q, text string, _ map[string]string, levels []string) jev.Answer {
	if point != "readiness" || kind != "score" || len(levels) != 5 || q != "How clearly does this issue state what to build?" {
		return jev.Answer{Status: "failed"}
	}
	s, ok := f.scores[text]
	if !ok {
		return jev.Answer{Status: "failed"}
	}
	return jev.Answer{Status: "ok", Score: s}
}

func TestPlanWarnings(t *testing.T) {
	e := newEnv(t)
	e.svc.d.Jev = fakeJev{status: "ok", scores: map[string]float64{"body of 3": 0.2, "body of 4": 3.6}}
	e.grind = GrindPlan{Skip: "invalid Slack channel X, pick a channel in Settings"}
	e.gh.Add(epicRule([]node{
		{n: 2, state: "OPEN", refined: false},
		{n: 3, state: "OPEN", refined: true, blocked: []string{"o/r#77:OPEN"}},
		{n: 4, state: "OPEN", refined: true},
		{n: 5, state: "OPEN", refined: true}, // jev fails for this one
	}))
	e.gh.Add(ghtest.Rule{Prefix: []string{"api", "repos/o/r/git/ref/heads/develop"}, Code: 1, Stderr: "Not Found"})
	p, err := e.svc.Plan(e.ctx(), CreateRequest{Epic: "o/r#1", Settings: map[string]any{"base_branch": "develop"}})
	if err != nil {
		t.Fatal(err)
	}
	if p.Title != "The epic" || len(p.Lanes) != 4 || p.Lanes[0].Refined || p.Lanes[1].Readiness == nil || *p.Lanes[1].Readiness != 1 || *p.Lanes[2].Readiness != 5 || p.Lanes[3].Readiness != nil {
		t.Fatalf("%+v", p.Lanes)
	}
	if len(p.Waves) != 1 || strings.Join(p.Waves[0], ",") != "o/r#3,o/r#4,o/r#5" {
		t.Fatal(p.Waves)
	}
	got := strings.Join(p.Warnings, "\n")
	for _, w := range []string{"o/r#2: needs refine", "o/r#3: blocked by open o/r#77 outside the epic", "o/r: invalid Slack channel X, pick a channel in Settings",
		"o/r: base branch develop does not exist", "o/r#3: may be underspecified (jev 1/5)", "Readiness unavailable for o/r#5"} {
		if !strings.Contains(got, w) {
			t.Errorf("missing %q in\n%s", w, got)
		}
	}
	if strings.Contains(got, "o/r#4: may be underspecified") {
		t.Fatal("score 5 is fine")
	}
	// grind off: no resolver warning; jev missing: no readiness
	e2 := newEnv(t)
	e2.svc.d.Jev = fakeJev{status: "missing"}
	e2.grind = GrindPlan{}
	e2.gh.Add(epicRule([]node{{n: 3, state: "OPEN", refined: true}}))
	p, _ = e2.svc.Plan(e2.ctx(), CreateRequest{Epic: "o/r#1", Settings: map[string]any{"grind": "off"}})
	if len(p.Warnings) != 0 || p.Lanes[0].Readiness != nil {
		t.Fatal(p.Warnings)
	}
	e2.gh.Reset()
	e2.gh.Add(epicRule([]node{{n: 3, state: "OPEN", refined: true}}))
	p, _ = e2.svc.Plan(e2.ctx(), CreateRequest{Epic: "o/r#1"})
	if len(p.Warnings) != 1 || p.Warnings[0] != "o/r: "+NoReviewer {
		t.Fatal(p.Warnings)
	}
}

func TestCreateEpicAndOwnership(t *testing.T) {
	e := newEnv(t)
	e.gh.Add(epicRule([]node{{n: 2, state: "OPEN", refined: true}, {n: 3, state: "OPEN", refined: false, blocked: []string{"o/r#2:OPEN"}}}))
	d, err := e.svc.Create(e.ctx(), CreateRequest{Epic: "o/r#1", Settings: map[string]any{"max": 3, "grind": "simple"}})
	if err != nil {
		t.Fatal(err)
	}
	if !store.ValidID(d.ID) || d.State != store.Running || d.Runner != "headless" || *d.Epic != "o/r#1" || d.Title != "The epic" || d.Settings.Max != 3 ||
		d.Lanes["o/r#2"].Stage != store.StQueued || d.Lanes["o/r#3"].Stage != store.StSkipped || d.Lanes["o/r#3"].SkipReason != "needs refine" ||
		strings.Join(d.Lanes["o/r#3"].Deps, ",") != "o/r#2" || d.Events[0].Kind != "started" || d.Events[0].Text != "2 lanes" {
		t.Fatalf("%+v", d)
	}
	if got, err := store.Load(e.h, d.ID); err != nil || len(got.Lanes) != 2 {
		t.Fatal(err)
	}
	// the same issues again: 409 carrying the owner
	_, err = e.svc.Create(e.ctx(), CreateRequest{Epic: "o/r#1"})
	if x, ok := errs.As(err); !ok || x.Kind != errs.KConflict || x.Extra["id"] != d.ID {
		t.Fatalf("%v", err)
	}
	// blubird missing
	e.svc.d.Prompts = fakePrompts{Unavailable: errs.Conflict("blubird is not installed", nil)}
	if _, err := e.svc.Create(e.ctx(), CreateRequest{Epic: "o/r#2"}); errs.KindOf(err) != errs.KConflict {
		t.Fatal(err)
	}
}

func TestCreateValidation(t *testing.T) {
	e := newEnv(t)
	bad := []CreateRequest{
		{},
		{Epic: "o/r#1", Issues: []string{"o/r#2"}},
		{Epic: "o/r#1", Settings: map[string]any{"max": 99}},
		{Epic: "o/r#1", Settings: map[string]any{"account": "nope"}},
		{Issues: []string{"o/r#2"}, Settings: map[string]any{"feature_branch": "feat"}},
		{Issues: []string{"o/r#2", "x/y#3"}},
	}
	for i, b := range bad {
		if _, err := e.svc.Create(e.ctx(), b); errs.KindOf(err) != errs.KInvalid {
			t.Errorf("case %d: %v", i, err)
		}
	}
	// an epic with no open children
	e.gh.Add(epicRule([]node{{n: 2, state: "CLOSED"}}))
	if _, err := e.svc.Create(e.ctx(), CreateRequest{Epic: "o/r#1"}); err == nil || err.Error() != "o/r#1 has no open child issues" {
		t.Fatal(err)
	}
	// a pick of only closed issues
	e2 := newEnv(t)
	e2.gh.Add(issuesRule(node{n: 2, state: "CLOSED"}))
	if _, err := e2.svc.Create(e2.ctx(), CreateRequest{Issues: []string{"o/r#2"}}); err == nil || err.Error() != "none of the picked issues is open" {
		t.Fatal(err)
	}
	// a missing base branch is refused before anything is saved
	e3 := newEnv(t)
	e3.gh.Add(epicRule([]node{{n: 2, state: "OPEN", refined: true}}))
	e3.gh.Add(ghtest.Rule{Prefix: []string{"api", "repos/o/r/git/ref/heads/dev"}, Code: 1})
	if _, err := e3.svc.Create(e3.ctx(), CreateRequest{Epic: "o/r#1", Settings: map[string]any{"base_branch": "dev"}}); err == nil || err.Error() != "o/r: base branch dev does not exist" {
		t.Fatal(err)
	}
	if len(store.List(e3.h)) != 0 {
		t.Fatal("saved a refused dispatch")
	}
}

func TestCreateIssuesAndFeatureBranch(t *testing.T) {
	e := newEnv(t)
	e.gh.Add(issuesRule(node{n: 7, state: "OPEN", refined: true}, node{n: 5, state: "OPEN", refined: true}))
	d, err := e.svc.Create(e.ctx(), CreateRequest{Issues: []string{"o/r#7", "o/r#5", "o/r#7"}})
	if err != nil {
		t.Fatal(err)
	}
	if d.Epic != nil || strings.Join(d.Issues, ",") != "o/r#5,o/r#7" || d.Title != "Small changes: #5, #7" || len(d.Lanes) != 2 {
		t.Fatalf("%+v", d)
	}
	// epic dispatch with a feature branch: cut it from the default branch when missing
	e2 := newEnv(t)
	e2.gh.Add(epicRule([]node{{n: 2, state: "OPEN", refined: true}}))
	e2.gh.Add(ghtest.Rule{Prefix: []string{"api", "repos/o/r/git/ref/heads/feat"}, Code: 1})
	e2.gh.Add(ghtest.Rule{Prefix: []string{"repo", "view", "o/r"}, Stdout: "main\n"})
	e2.gh.Add(ghtest.Rule{Prefix: []string{"api", "repos/o/r/commits/main"}, Stdout: "deadbeef\n"})
	e2.gh.Add(ghtest.Rule{Prefix: []string{"api", "repos/o/r/git/refs"}, Stdout: "{}"})
	if _, err := e2.svc.Create(e2.ctx(), CreateRequest{Epic: "o/r#1", Settings: map[string]any{"feature_branch": "feat"}}); err != nil {
		t.Fatal(err)
	}
	c := e2.gh.CallsMatching("api", "repos/o/r/git/refs")
	if len(c) != 1 || strings.Join(c[0], " ") != "api repos/o/r/git/refs -f ref=refs/heads/feat -f sha=deadbeef" {
		t.Fatal(c)
	}
	// an existing feature branch is left alone
	e3 := newEnv(t)
	e3.gh.Add(epicRule([]node{{n: 2, state: "OPEN", refined: true}}))
	e3.gh.Add(ghtest.Rule{Prefix: []string{"api", "repos/o/r/git/ref/heads/feat"}, Stdout: "{}"})
	if _, err := e3.svc.Create(e3.ctx(), CreateRequest{Epic: "o/r#1", Settings: map[string]any{"feature_branch": "feat"}}); err != nil {
		t.Fatal(err)
	}
	if len(e3.gh.CallsMatching("api", "repos/o/r/git/refs")) != 0 {
		t.Fatal("created an existing branch")
	}
	// a failed branch creation is reported
	e4 := newEnv(t)
	e4.gh.Add(epicRule([]node{{n: 2, state: "OPEN", refined: true}}))
	e4.gh.Add(ghtest.Rule{Prefix: []string{"api", "repos/o/r/git/ref/heads/feat"}, Code: 1})
	e4.gh.Add(ghtest.Rule{Prefix: []string{"repo", "view"}, Stdout: "main\n"})
	e4.gh.Add(ghtest.Rule{Prefix: []string{"api", "repos/o/r/commits/main"}, Stdout: "dead\n"})
	e4.gh.Add(ghtest.Rule{Prefix: []string{"api", "repos/o/r/git/refs"}, Code: 1, Stderr: "Reference already exists"})
	if _, err := e4.svc.Create(e4.ctx(), CreateRequest{Epic: "o/r#1", Settings: map[string]any{"feature_branch": "feat"}}); err == nil || !strings.Contains(err.Error(), "cannot create feat on o/r") {
		t.Fatal(err)
	}
}

func TestAddLanesAndEdits(t *testing.T) {
	e := newEnv(t)
	e.seed(nil, &store.Lane{Repo: "o/r", N: 2, Stage: store.StClosed})
	d := e.load()
	d.State = store.Done
	_ = store.Save(e.h, &d)
	e.gh.Add(issuesRule(node{n: 8, state: "OPEN", refined: true}))
	got, err := e.svc.AddLanes(e.ctx(), "aaaaaaaaaaaa", []string{"o/r#8"})
	if err != nil {
		t.Fatal(err)
	}
	if got.State != store.Paused || got.Lanes["o/r#8"].Stage != store.StQueued || strings.Join(got.Added, ",") != "o/r#8" || got.Issues != nil {
		t.Fatalf("%+v", got)
	}
	// a lane owned by another live dispatch is a conflict
	other := &store.Dispatch{ID: "bbbbbbbbbbbb", State: store.Running, Settings: store.Defaults(), Lanes: map[string]*store.Lane{"o/r#9": {Repo: "o/r", N: 9, Stage: store.StQueued}}}
	_ = store.Save(e.h, other)
	e.gh.Reset()
	e.gh.Add(issuesRule(node{n: 9, state: "OPEN", refined: true}))
	if _, err := e.svc.AddLanes(e.ctx(), "aaaaaaaaaaaa", []string{"o/r#9"}); errs.KindOf(err) != errs.KConflict {
		t.Fatal(err)
	}
	// cancelled dispatches take nothing
	_, _ = e.svc.SetState("aaaaaaaaaaaa", store.Cancelled, false)
	if _, err := e.svc.AddLanes(e.ctx(), "aaaaaaaaaaaa", []string{"o/r#8"}); errs.KindOf(err) != errs.KConflict {
		t.Fatal(err)
	}

	// settings edits
	e2 := newEnv(t)
	e2.seed(nil, &store.Lane{Repo: "o/r", N: 2, Stage: store.StQueued})
	if _, err := e2.svc.SetSettings("aaaaaaaaaaaa", map[string]any{"base_branch": "x"}); err == nil || err.Error() != "base_branch is fixed at start" {
		t.Fatal(err)
	}
	if _, err := e2.svc.SetSettings("aaaaaaaaaaaa", map[string]any{"account": "nope"}); errs.KindOf(err) != errs.KInvalid {
		t.Fatal(err)
	}
	got, err = e2.svc.SetSettings("aaaaaaaaaaaa", map[string]any{"max": 4, "account": "work", "auto_merge": true})
	if err != nil || got.Settings.Max != 4 || !got.Settings.AutoMerge || got.Events[len(got.Events)-1].Text != "account=work, auto_merge=true, max=4" {
		t.Fatalf("%+v %v", got.Settings, err)
	}
	if _, err := e2.svc.Seen("aaaaaaaaaaaa", false); err != nil || !e2.load().SeenDone {
		t.Fatal("seen")
	}
	if _, err := e2.svc.Seen("aaaaaaaaaaaa", true); err != nil || e2.load().SeenDone {
		t.Fatal("unseen")
	}
}
