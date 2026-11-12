package poller

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/masnun-siam/setu/internal/events"
	"github.com/masnun-siam/setu/internal/execx"
	"github.com/masnun-siam/setu/internal/gh/ghtest"
)

var t0 = time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC)

type fx struct {
	t  *testing.T
	mu sync.Mutex
	c  *ghtest.Client
	p  *Poller
	// responses
	probe     string
	full      string
	pages     []string // follow-up issue pages, in order
	projects  string
	projectsX *execx.Result // overrides projects when set
	fail      *execx.Result // makes every call fail
	// counters
	probes, fulls, pageCalls, projectCalls int
	now                                    time.Time
	bus                                    *events.Bus
}

func (f *fx) clock() time.Time { f.mu.Lock(); defer f.mu.Unlock(); return f.now }
func (f *fx) advance(d time.Duration) {
	f.mu.Lock()
	f.now = f.now.Add(d)
	f.mu.Unlock()
}

func newFx(t *testing.T) *fx {
	f := &fx{t: t, now: t0, bus: events.New()}
	f.probe = probeResp("a", 4000)
	f.full = fullResp("[]", "[]", "[]", false, 4000)
	f.projects = projectsResp("[]", false)
	f.c = ghtest.New(ghtest.Rule{Prefix: []string{"api", "graphql"}, Func: f.answer})
	f.p = New(f.c, f.bus, Options{Now: f.clock, Watched: func() []string { return []string{"o/r"} }})
	return f
}

func (f *fx) answer(args []string) execx.Result {
	f.mu.Lock()
	defer f.mu.Unlock()
	q := ""
	for _, a := range args {
		if strings.HasPrefix(a, "query=") {
			q = a
		}
	}
	if f.fail != nil {
		return *f.fail
	}
	ok := func(s string) execx.Result { return execx.Result{Stdout: []byte(s)} }
	switch {
	case strings.Contains(q, "pullRequests(first: 1"):
		f.probes++
		return ok(f.probe)
	case strings.Contains(q, "closedEpics"):
		f.fulls++
		return ok(f.full)
	case strings.Contains(q, "projectItems"):
		f.projectCalls++
		if f.projectsX != nil {
			return *f.projectsX
		}
		return ok(f.projects)
	case strings.Contains(q, "closedByPullRequestsReferences"):
		f.pageCalls++
		i := f.pageCalls - 1
		if i >= len(f.pages) {
			return execx.Result{Code: 1, Stderr: []byte("no page")}
		}
		return ok(f.pages[i])
	}
	return execx.Result{Code: 99, Stderr: []byte("unexpected query")}
}

func rl(remaining int) string {
	return fmt.Sprintf(`"rateLimit":{"cost":1,"remaining":%d,"resetAt":%q}`, remaining, t0.Add(30*time.Minute).Format(time.RFC3339))
}

func probeResp(tag string, remaining int) string {
	return fmt.Sprintf(`{"data":{"repository":{"issues":{"totalCount":1,"nodes":[{"updatedAt":%q}]},"pullRequests":{"totalCount":0,"nodes":[]},"openPrs":{"nodes":[]}},%s}}`, tag, rl(remaining))
}

func fullResp(issues, merged, open string, hasNext bool, remaining int) string {
	return fmt.Sprintf(`{"data":{"repository":{"issues":{"pageInfo":{"hasNextPage":%v,"endCursor":"C1"},"nodes":%s},"closedEpics":{"nodes":[]},"mergedPrs":{"nodes":%s},"openPrs":{"nodes":%s}},%s}}`,
		hasNext, issues, merged, open, rl(remaining))
}

func pageResp(issues string, hasNext bool) string {
	return fmt.Sprintf(`{"data":{"repository":{"issues":{"pageInfo":{"hasNextPage":%v,"endCursor":"C2"},"nodes":%s}},%s}}`, hasNext, issues, rl(3000))
}

func projectsResp(nodes string, hasNext bool) string { return projectsRespRem(nodes, hasNext, 4000) }

func projectsRespRem(nodes string, hasNext bool, remaining int) string {
	return fmt.Sprintf(`{"data":{"repository":{"issues":{"pageInfo":{"hasNextPage":%v,"endCursor":"P"},"nodes":%s}},%s}}`, hasNext, nodes, rl(remaining))
}

func issueJSON(n int, extra string) string {
	return fmt.Sprintf(`{"number":%d,"title":"issue %d","state":"OPEN","labels":{"nodes":[]},"parent":null,"subIssues":{"nodes":[]},"blockedBy":{"nodes":[]},"closedByPullRequestsReferences":{"nodes":[]}%s}`, n, n, extra)
}

func prNode(n int, extra string) string {
	return fmt.Sprintf(`{"number":%d,"url":"https://github.com/o/r/pull/%d","isDraft":false,"state":"OPEN","mergedAt":null,"headRefName":"feat-%d","headRefOid":"sha%d","reviewDecision":null,"mergeable":"MERGEABLE","statusCheckRollup":{"state":"SUCCESS"},"title":"pr %d","body":""%s}`, n, n, n, n, n, extra)
}

func (f *fx) poll(full bool) Snapshot { return f.p.Poll(context.Background(), "o/r", full) }

func TestProbeSkipsFullQuery(t *testing.T) {
	f := newFx(t)
	s := f.poll(false)
	if s.Stale || s.FetchedAt == nil || f.probes != 1 || f.fulls != 1 {
		t.Fatalf("first poll: %v probes=%d fulls=%d", s, f.probes, f.fulls)
	}
	f.advance(61 * time.Second)
	f.poll(false)
	if f.probes != 2 || f.fulls != 1 {
		t.Fatalf("unchanged answer must not run the full query: probes=%d fulls=%d", f.probes, f.fulls)
	}
	f.poll(true)
	if f.fulls != 2 {
		t.Fatalf("full=true: fulls=%d", f.fulls)
	}
	f.probe = probeResp("b", 4000)
	f.poll(false)
	if f.fulls != 3 {
		t.Fatalf("changed answer: fulls=%d", f.fulls)
	}
	f.advance(FullEvery + time.Second)
	f.poll(false)
	if f.fulls != 4 {
		t.Fatalf("FULL_EVERY elapsed: fulls=%d", f.fulls)
	}
}

func TestSnapshotBeforeFirstFetch(t *testing.T) {
	f := newFx(t)
	s := f.p.Snapshot("o/r")
	if !s.Stale || s.FetchedAt != nil || s.RetryAt != nil || s.Error != "" || !s.Data.Empty() || s.Data.Issues == nil || s.Data.Merged == nil || s.Data.OpenPRs == nil || s.Data.ClosedEpics == nil {
		t.Fatalf("%+v", s)
	}
	if f.probes != 0 {
		t.Fatal("snapshot must not call gh")
	}
	b, _ := json.Marshal(s.Data)
	if !strings.Contains(string(b), `"issues":[]`) {
		t.Fatal(string(b))
	}
}

func TestCadence(t *testing.T) {
	f := newFx(t)
	f.poll(false)
	if f.p.due("o/r", true) {
		t.Fatal("due right after a poll")
	}
	f.advance(59 * time.Second)
	if f.p.due("o/r", true) {
		t.Fatal("due before 60 s")
	}
	f.advance(2 * time.Second)
	if !f.p.due("o/r", true) {
		t.Fatal("not due after 60 s")
	}
	// cold repo: only every 600 s
	if f.p.due("o/r", false) {
		t.Fatal("cold repo due after 61 s")
	}
	f.advance(600 * time.Second)
	if !f.p.due("o/r", false) {
		t.Fatal("cold repo not due after 600 s")
	}

	// pending CI: 15 s cadence
	f2 := newFx(t)
	f2.full = fullResp("[]", "[]", "["+prNode(1, "")[:0]+strings.Replace(prNode(1, ""), `"state":"SUCCESS"`, `"state":"PENDING"`, 1)+"]", false, 4000)
	f2.poll(false)
	f2.advance(14 * time.Second)
	if f2.p.due("o/r", true) {
		t.Fatal("pending: due before 15 s")
	}
	f2.advance(2 * time.Second)
	if !f2.p.due("o/r", true) {
		t.Fatal("pending: not due after 15 s")
	}

	// low budget forces 600 s even with pending CI
	f3 := newFx(t)
	f3.probe = probeResp("a", 999)
	f3.projects = projectsRespRem("[]", false, 999)
	f3.full = strings.Replace(f2.full, `"remaining":4000`, `"remaining":999`, 1)
	f3.poll(false) // budget learned from this response's rateLimit
	f3.poll(true)
	f3.advance(30 * time.Second) // still inside the reset window (30 min)
	if f3.p.due("o/r", true) {
		t.Fatal("low budget: due after 30 s")
	}
	f3.advance(10 * time.Minute)
	if f3.p.Budget().Remaining != 999 {
		t.Fatalf("budget %+v", f3.p.Budget())
	}
	if !f3.p.due("o/r", true) {
		t.Fatal("low budget: not due after 600 s")
	}
}

func TestRateLimit(t *testing.T) {
	f := newFx(t)
	f.poll(false)
	good := f.p.Snapshot("o/r").Data
	_ = good
	f.advance(61 * time.Second)
	f.fail = &execx.Result{Code: 1, Stderr: []byte("gh: API rate limit exceeded for user")}
	s := f.poll(false)
	if !s.Stale || s.Error != "rate limited" || s.RetryAt == nil || !s.RetryAt.Equal(f.clock().Add(RateLimitPause)) {
		t.Fatalf("secondary limit: %+v", s)
	}
	n := f.probes
	f.fail = nil
	f.advance(time.Minute)
	if s2 := f.poll(false); f.probes != n || s2.RetryAt == nil || !s2.Stale {
		t.Fatalf("calls while paused: probes %d vs %d, %+v", f.probes, n, s2)
	}
	if f.p.due("o/r", true) {
		t.Fatal("due while paused")
	}
	f.advance(RateLimitPause)
	s = f.poll(false)
	if s.Stale || s.Error != "" || s.RetryAt != nil {
		t.Fatalf("recovery: %+v", s)
	}

	// primary limit with a low budget pauses until the reset
	g := newFx(t)
	g.probe = probeResp("a", 5)
	g.projects = projectsRespRem("[]", false, 5)
	g.full = strings.Replace(g.full, `"remaining":4000`, `"remaining":5`, 1)
	g.poll(false) // learn remaining=5
	g.advance(61 * time.Second)
	g.fail = &execx.Result{Stdout: []byte(`{"errors":[{"type":"RATE_LIMITED","message":"x"}]}`)}
	s = g.poll(false)
	if s.Error != "rate limited" || s.RetryAt == nil || !s.RetryAt.Equal(t0.Add(30*time.Minute)) {
		t.Fatalf("primary limit: %+v", s)
	}
}

func TestOtherFailureKeepsDataAndRetries(t *testing.T) {
	f := newFx(t)
	f.full = fullResp("["+issueJSON(1, "")+"]", "[]", "[]", false, 4000)
	f.poll(false)
	f.advance(61 * time.Second)
	f.fail = &execx.Result{Code: 1, Stderr: []byte("HTTP 502 bad gateway")}
	s := f.poll(false)
	if !s.Stale || s.Error != "HTTP 502 bad gateway" || s.RetryAt != nil || len(s.Data.Issues) != 1 {
		t.Fatalf("%+v", s)
	}
	f.advance(61 * time.Second)
	if !f.p.due("o/r", true) {
		t.Fatal("must retry on the normal cadence")
	}
	f.fail = nil
	if s = f.poll(false); s.Stale || s.Error != "" {
		t.Fatalf("%+v", s)
	}
	// graphql errors in the payload
	f.advance(61 * time.Second)
	f.fail = &execx.Result{Stdout: []byte(`{"errors":[{"type":"NOT_FOUND","message":"Could not resolve to a Repository"}]}`)}
	s = f.poll(false)
	if !s.Stale || !strings.Contains(s.Error, "Could not resolve") || len(s.Error) > 200 {
		t.Fatalf("%+v", s)
	}
}

func TestMalformedRepositoryIsStale(t *testing.T) {
	f := newFx(t)
	f.full = `{"data":{"repository":null,` + rl(4000) + `}}`
	s := f.poll(false)
	if !s.Stale || s.Error != "no repository in the GraphQL response" {
		t.Fatalf("%+v", s)
	}
}

func TestTruncationAndFailingPage(t *testing.T) {
	f := newFx(t)
	f.full = fullResp("["+issueJSON(1, "")+"]", "[]", "[]", true, 4000)
	for i := 0; i < 4; i++ {
		f.pages = append(f.pages, pageResp("["+issueJSON(10+i, "")+"]", true))
	}
	s := f.poll(false)
	if f.pageCalls != 4 || !s.Data.IssuesTruncated || len(s.Data.Issues) != 5 || s.Stale {
		t.Fatalf("pages=%d truncated=%v issues=%d", f.pageCalls, s.Data.IssuesTruncated, len(s.Data.Issues))
	}
	// a page that ends the list: not truncated
	g := newFx(t)
	g.full = fullResp("["+issueJSON(1, "")+"]", "[]", "[]", true, 4000)
	g.pages = []string{pageResp("["+issueJSON(2, "")+"]", false)}
	if s = g.poll(false); g.pageCalls != 1 || s.Data.IssuesTruncated || len(s.Data.Issues) != 2 {
		t.Fatalf("%v pages=%d", s, g.pageCalls)
	}
	// a failing page makes the whole fetch stale and keeps old data
	h := newFx(t)
	h.full = fullResp("["+issueJSON(1, "")+"]", "[]", "[]", false, 4000)
	h.poll(false)
	h.advance(61 * time.Second)
	h.probe = probeResp("changed", 4000)
	h.full = fullResp("["+issueJSON(2, "")+"]", "[]", "[]", true, 4000)
	s = h.poll(false) // page 1 has no rule: fails
	if !s.Stale || len(s.Data.Issues) != 1 || s.Data.Issues[0].N != 1 {
		t.Fatalf("%+v", s)
	}
}

func TestNormalizeIssues(t *testing.T) {
	issues := `[{"number":5,"title":"Epic: big","state":"OPEN","labels":{"nodes":[{"name":"epic"},{"name":"Priority: High "},{"name":"priority:low"},null]},
	  "parent":{"number":2,"repository":{"nameWithOwner":"o/docs"}},
	  "subIssues":{"nodes":[{"number":6,"title":"six","state":"OPEN","repository":{"nameWithOwner":"o/code"}},{"number":7,"title":"seven","state":"CLOSED"},null]},
	  "blockedBy":{"nodes":[{"number":3,"state":"OPEN","repository":{"nameWithOwner":"o/other"}},{"number":4,"state":"CLOSED"}]},
	  "closedByPullRequestsReferences":{"nodes":[` + strings.Replace(prNode(9, ""), `"state":"SUCCESS"`, `"state":"EXPECTED"`, 1) + `]}}]`
	var resp response
	if err := json.Unmarshal([]byte(fullResp(issues, "[]", "[]", false, 1)), &resp); err != nil {
		t.Fatal(err)
	}
	d, err := normalize("o/r", &resp, nil, t0)
	if err != nil {
		t.Fatal(err)
	}
	is := d.Issues[0]
	if *is.Priority != "High" || is.Parent.String() != "o/docs#2" || len(is.SubIssues) != 2 || is.SubIssues[0].String() != "o/code#6" || is.SubIssues[1].String() != "o/r#7" {
		t.Fatalf("%+v", is)
	}
	if len(is.ClosedSubs) != 1 || is.ClosedSubs[0].N != 7 || is.ClosedSubs[0].Repo != "o/r" || is.ClosedSubs[0].Title != "seven" {
		t.Fatalf("%+v", is.ClosedSubs)
	}
	if len(is.BlockedBy) != 2 || is.BlockedBy[0].String() != "o/other#3" || is.BlockedBy[0].State != "OPEN" || is.BlockedBy[1].State != "CLOSED" {
		t.Fatalf("%+v", is.BlockedBy)
	}
	if p := is.PRs[0]; p.CI != "pending" || p.Review != "none" || p.Conflict || p.SHA != "sha9" || p.Head != "feat-9" {
		t.Fatalf("%+v", p)
	}
	b, _ := json.Marshal(is.ClosedSubs[0])
	if string(b) != `{"repo":"o/r","n":7,"title":"seven"}` {
		t.Fatal(string(b))
	}
}

func TestPRDerivation(t *testing.T) {
	cases := []struct {
		name, state, decision, mergeable, ci, review string
		conflict                                     bool
	}{
		{"success approved", "SUCCESS", "APPROVED", "MERGEABLE", "success", "approved", false},
		{"failure", "FAILURE", "CHANGES_REQUESTED", "CONFLICTING", "failure", "changes_requested", true},
		{"error is failure", "ERROR", "REVIEW_REQUIRED", "MERGEABLE", "failure", "review_required", false},
		{"expected pending", "EXPECTED", "", "UNKNOWN", "pending", "none", false},
		{"no rollup", "", "", "UNKNOWN", "none", "none", false},
		{"odd rollup", "WEIRD", "", "", "none", "none", false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			rollup := "null"
			if tc.state != "" {
				rollup = fmt.Sprintf(`{"state":%q}`, tc.state)
			}
			dec := "null"
			if tc.decision != "" {
				dec = fmt.Sprintf("%q", tc.decision)
			}
			n := fmt.Sprintf(`{"number":1,"url":"u","isDraft":false,"state":"OPEN","headRefName":"h","headRefOid":"s","reviewDecision":%s,"mergeable":%q,"statusCheckRollup":%s}`, dec, tc.mergeable, rollup)
			var pr gqlPR
			if err := json.Unmarshal([]byte(n), &pr); err != nil {
				t.Fatal(err)
			}
			got := prOf(&pr)
			if got.CI != tc.ci || got.Review != tc.review || got.Conflict != tc.conflict {
				t.Fatalf("%+v", got)
			}
		})
	}
}

func TestOpenPRReviewState(t *testing.T) {
	review := func(state, login string) string {
		return fmt.Sprintf(`{"state":%q,"author":{"login":%q}}`, state, login)
	}
	threads := `{"nodes":[{"isResolved":true,"isOutdated":false},{"isResolved":false,"isOutdated":true},{"isResolved":false,"isOutdated":false},{"isResolved":false,"isOutdated":false}]}`
	mk := func(decision, reviews string) OpenPR {
		extra := fmt.Sprintf(`,"latestOpinionatedReviews":{"nodes":[%s]},"checks":{"contexts":{"totalCount":7}},"reviewThreads":%s`, reviews, threads)
		n := strings.Replace(prNode(1, extra), `"reviewDecision":null`, fmt.Sprintf(`"reviewDecision":%s`, decision), 1)
		var resp response
		if err := json.Unmarshal([]byte(fullResp("[]", "[]", "["+n+"]", false, 1)), &resp); err != nil {
			t.Fatal(err)
		}
		d, err := normalize("o/r", &resp, nil, t0)
		if err != nil {
			t.Fatal(err)
		}
		return d.OpenPRs[0]
	}
	p := mk(`"APPROVED"`, review("APPROVED", "ann")+","+review("APPROVED", "bob"))
	if !p.Approved || p.ChangesRequested || *p.Reviewer != "bob" || p.ThreadsOpen != 2 || p.Checks != 7 {
		t.Fatalf("%+v", p)
	}
	// one CHANGES_REQUESTED defeats another reviewer's approval, even with decision approved
	p = mk(`"APPROVED"`, review("APPROVED", "ann")+","+review("CHANGES_REQUESTED", "bob"))
	if p.Approved || !p.ChangesRequested {
		t.Fatalf("%+v", p)
	}
	// no review rule (decision none) with an approver is approved
	p = mk("null", review("APPROVED", "ann"))
	if !p.Approved || p.Review != "none" {
		t.Fatalf("%+v", p)
	}
	// decision none, nobody approved
	p = mk("null", review("COMMENTED", "ann"))
	if p.Approved || p.Reviewer != nil {
		t.Fatalf("%+v", p)
	}
	// review required with an approver is not approved
	p = mk(`"REVIEW_REQUIRED"`, review("APPROVED", "ann"))
	if p.Approved {
		t.Fatalf("%+v", p)
	}
	// CHANGES_REQUESTED decision
	p = mk(`"CHANGES_REQUESTED"`, "")
	if !p.ChangesRequested || p.Approved {
		t.Fatalf("%+v", p)
	}
}

func TestPRAttachmentByBodyAndBranch(t *testing.T) {
	issues := "[" + issueJSON(7, "") + "," + issueJSON(6, "") + "," + issueJSON(8, "") + "]"
	open := `[{"number":20,"url":"u","isDraft":true,"state":"OPEN","mergedAt":null,"headRefName":"issue-7-thing","headRefOid":"s","reviewDecision":null,"mergeable":"MERGEABLE","statusCheckRollup":null,"title":"t","body":"Closes #6, and fixes: #8 too","closingIssuesReferences":{"nodes":[]}}]`
	var resp response
	_ = json.Unmarshal([]byte(fullResp(issues, "[]", open, false, 1)), &resp)
	d, err := normalize("o/r", &resp, nil, t0)
	if err != nil {
		t.Fatal(err)
	}
	for _, is := range d.Issues {
		if len(is.PRs) != 1 || is.PRs[0].N != 20 || is.PRs[0].State != "OPEN" || !is.PRs[0].Draft {
			t.Fatalf("issue %d: %+v", is.N, is.PRs)
		}
	}
	if fmt.Sprint(d.OpenPRs[0].Refs) != "[6 8 7]" {
		t.Fatalf("refs %v", d.OpenPRs[0].Refs)
	}
	// already linked by GitHub: no duplicate
	open2 := strings.Replace(open, `"closingIssuesReferences":{"nodes":[]}`, `"closingIssuesReferences":{"nodes":[{"number":7}]}`, 1)
	issues2 := "[" + issueJSON(7, `,"closedByPullRequestsReferences2":1`)[:0] + strings.Replace(issueJSON(7, ""), `"closedByPullRequestsReferences":{"nodes":[]}`, `"closedByPullRequestsReferences":{"nodes":[`+prNode(20, "")+`]}`, 1) + "]"
	resp = response{}
	_ = json.Unmarshal([]byte(fullResp(issues2, "[]", open2, false, 1)), &resp)
	d, _ = normalize("o/r", &resp, nil, t0)
	if len(d.Issues[0].PRs) != 1 {
		t.Fatalf("%+v", d.Issues[0].PRs)
	}
}

func TestMergedPRs(t *testing.T) {
	merged := func(n int, at time.Time, head, body, closing string) string {
		return fmt.Sprintf(`{"number":%d,"title":"m%d","url":"u%d","mergedAt":%q,"headRefName":%q,"headRefOid":"sha%d","body":%q,"closingIssuesReferences":{"nodes":[%s]}}`,
			n, n, n, at.Format(time.RFC3339), head, n, body, closing)
	}
	issues := "[" + strings.Replace(issueJSON(30, ""), `"parent":null`, `"parent":{"number":3,"repository":{"nameWithOwner":"o/docs"}}`, 1) + "," + issueJSON(31, "") + "]"
	list := "[" +
		merged(1, t0.Add(-time.Hour), "issue-30-x", "", "") + "," + // staging merge, issue still open: epic from the open issue's parent
		merged(2, t0.Add(-8*24*time.Hour), "old", "", "") + "," + // outside the window
		merged(3, t0.Add(-2*time.Hour), "feature", "", `{"number":40,"parent":{"number":4,"repository":{"nameWithOwner":"o/docs"}}}`) + "," + // linked by GitHub
		merged(4, t0.Add(-3*time.Hour), "other", "Fixes #31", "") + "," +
		`{"number":5,"mergedAt":null}` +
		"]"
	var resp response
	if err := json.Unmarshal([]byte(fullResp(issues, list, "[]", false, 1)), &resp); err != nil {
		t.Fatal(err)
	}
	d, err := normalize("o/r", &resp, nil, t0)
	if err != nil {
		t.Fatal(err)
	}
	if len(d.Merged) != 3 {
		t.Fatalf("%+v", d.Merged)
	}
	m1, m3, m4 := d.Merged[0], d.Merged[1], d.Merged[2]
	if m1.N != 1 || fmt.Sprint(m1.Closes) != "[30]" || m1.Epic == nil || m1.Epic.String() != "o/docs#3" || m1.SHA != "sha1" {
		t.Fatalf("%+v", m1)
	}
	if m3.Epic == nil || m3.Epic.String() != "o/docs#4" || fmt.Sprint(m3.Closes) != "[40]" {
		t.Fatalf("%+v", m3)
	}
	if m4.Epic != nil || fmt.Sprint(m4.Closes) != "[31]" {
		t.Fatalf("%+v", m4)
	}
	// merged into staging: the open issue shows the PR as MERGED
	is30 := d.Issues[0]
	if len(is30.PRs) != 1 || is30.PRs[0].State != "MERGED" || is30.PRs[0].CI != "success" || is30.PRs[0].N != 1 || is30.Status != StatusDone {
		t.Fatalf("%+v", is30)
	}
	if d.Issues[1].PRs[0].N != 4 {
		t.Fatalf("%+v", d.Issues[1].PRs)
	}
}

func TestClosedEpics(t *testing.T) {
	body := `{"data":{"repository":{"issues":{"pageInfo":{"hasNextPage":false},"nodes":[]},"closedEpics":{"nodes":[{"number":9,"labels":{"nodes":[{"name":"epic"},{"name":"prd-x"}]},"subIssues":{"nodes":[{"number":1,"title":"a","state":"CLOSED"},{"number":2,"title":"b","state":"OPEN"}]}}]},"mergedPrs":{"nodes":[]},"openPrs":{"nodes":[]}}}}`
	var resp response
	_ = json.Unmarshal([]byte(body), &resp)
	d, _ := normalize("o/r", &resp, nil, t0)
	e := d.ClosedEpics[0]
	if e.N != 9 || strings.Join(e.Labels, ",") != "epic,prd-x" || len(e.ClosedSubs) != 1 || e.ClosedSubs[0].N != 1 {
		t.Fatalf("%+v", e)
	}
}

func TestStatusDerivationAndProjects(t *testing.T) {
	issues := "[" +
		issueJSON(1, "") + "," + // backlog
		strings.Replace(issueJSON(2, ""), `"labels":{"nodes":[]}`, `"labels":{"nodes":[{"name":"refined"}]}`, 1) + "," + // ready
		strings.Replace(strings.Replace(issueJSON(3, ""), `"labels":{"nodes":[]}`, `"labels":{"nodes":[{"name":"refined"}]}`, 1), `"blockedBy":{"nodes":[]}`, `"blockedBy":{"nodes":[{"number":1,"state":"OPEN"}]}`, 1) + "," + // refined but blocked
		strings.Replace(issueJSON(4, ""), `"closedByPullRequestsReferences":{"nodes":[]}`, `"closedByPullRequestsReferences":{"nodes":[`+prNode(40, "")+`]}`, 1) + "," + // open PR
		issueJSON(5, "") + "," + // project says In progress
		strings.Replace(issueJSON(6, ""), `"labels":{"nodes":[]}`, `"labels":{"nodes":[{"name":"refined"}]}`, 1) + "," + // project says a custom column
		issueJSON(7, "") + // project says "in review" (case)
		"]"
	f := newFx(t)
	f.full = fullResp(issues, "[]", "[]", false, 4000)
	f.projects = projectsResp(`[
	  {"number":5,"projectItems":{"nodes":[{"fieldValueByName":null},{"fieldValueByName":{"name":"In progress"}}]}},
	  {"number":6,"projectItems":{"nodes":[{"fieldValueByName":{"name":"Blocked"}}]}},
	  {"number":7,"projectItems":{"nodes":[{"fieldValueByName":{"name":"in review"}}]}},
	  {"number":1,"projectItems":{"nodes":[]}}]`, false)
	s := f.poll(false)
	want := map[int][2]string{
		1: {"", StatusBacklog}, 2: {"", StatusReady}, 3: {"", StatusBacklog}, 4: {"", StatusInReview},
		5: {"In progress", StatusInProgress}, 6: {"Blocked", StatusReady}, 7: {"in review", StatusInReview},
	}
	for _, is := range s.Data.Issues {
		if w := want[is.N]; is.ProjectStatus != w[0] || is.Status != w[1] {
			t.Errorf("#%d: project=%q status=%q, want %v", is.N, is.ProjectStatus, is.Status, w)
		}
	}
	if f.projectCalls != 1 || s.Data.ProjectsNote != "" {
		t.Fatalf("projects calls=%d note=%q", f.projectCalls, s.Data.ProjectsNote)
	}
}

func TestProjectsUnavailableDerives(t *testing.T) {
	f := newFx(t)
	f.full = fullResp("["+strings.Replace(issueJSON(1, ""), `"labels":{"nodes":[]}`, `"labels":{"nodes":[{"name":"refined"}]}`, 1)+"]", "[]", "[]", false, 4000)
	f.projectsX = &execx.Result{Stdout: []byte(`{"errors":[{"type":"INSUFFICIENT_SCOPES","message":"Your token has not been granted the required scopes"}]}`)}
	s := f.poll(false)
	if s.Stale || s.Error != "" || len(s.Data.Issues) != 1 || s.Data.Issues[0].Status != StatusReady || !strings.HasPrefix(s.Data.ProjectsNote, "project status unavailable") {
		t.Fatalf("%+v note=%q", s, s.Data.ProjectsNote)
	}
	// not retried for an hour
	f.advance(61 * time.Second)
	f.poll(true)
	if f.projectCalls != 1 {
		t.Fatalf("project calls %d", f.projectCalls)
	}
	f.advance(time.Hour)
	f.projectsX = nil
	f.projects = projectsResp(`[{"number":1,"projectItems":{"nodes":[{"fieldValueByName":{"name":"Done"}}]}}]`, false)
	s = f.poll(true)
	if f.projectCalls != 2 || s.Data.Issues[0].Status != StatusDone || s.Data.ProjectsNote != "" {
		t.Fatalf("%+v", s.Data.Issues[0])
	}
}

func TestOnFreshGetsPrevAndSwallowsPanics(t *testing.T) {
	f := newFx(t)
	var got []string
	f.p.OnFresh(func(repo string, s Snapshot, prev Data) { panic("boom") })
	f.p.OnFresh(func(repo string, s Snapshot, prev Data) {
		got = append(got, fmt.Sprintf("%s issues=%d prevEmpty=%v fresh=%v", repo, len(s.Data.Issues), prev.Empty(), s.Fresh()))
	})
	f.full = fullResp("["+issueJSON(1, "")+"]", "[]", "[]", false, 4000)
	f.poll(false)
	f.advance(61 * time.Second)
	f.probe = probeResp("x", 4000)
	f.full = fullResp("["+issueJSON(1, "")+","+issueJSON(2, "")+"]", "[]", "[]", false, 4000)
	f.poll(false)
	f.advance(61 * time.Second)
	f.fail = &execx.Result{Code: 1, Stderr: []byte("down")}
	f.poll(false) // not fresh: no hook
	want := []string{"o/r issues=1 prevEmpty=true fresh=true", "o/r issues=2 prevEmpty=false fresh=true"}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("%v", got)
	}
}

func TestPublishOnlyOnChange(t *testing.T) {
	f := newFx(t)
	ch, cancel := f.bus.Subscribe(16)
	defer cancel()
	count := func() int {
		n := 0
		for {
			select {
			case ev := <-ch:
				if ev.Topic == events.TProducts {
					m := ev.Data.(map[string]any)
					if m["kind"] != "snapshot" || m["repo"] != "o/r" {
						t.Fatalf("payload %v", m)
					}
					n++
				}
			default:
				return n
			}
		}
	}
	f.poll(false)
	if n := count(); n != 1 {
		t.Fatalf("first poll published %d", n)
	}
	f.advance(61 * time.Second)
	f.poll(false) // nothing changed
	f.advance(61 * time.Second)
	f.poll(true) // full, identical data
	if n := count(); n != 0 {
		t.Fatalf("no change published %d", n)
	}
	f.probe = probeResp("b", 4000)
	f.full = fullResp("["+issueJSON(1, "")+"]", "[]", "[]", false, 4000)
	f.poll(false)
	if n := count(); n != 1 {
		t.Fatalf("data change published %d", n)
	}
	f.fail = &execx.Result{Code: 1, Stderr: []byte("down")}
	f.advance(61 * time.Second)
	f.poll(false) // stale flip
	f.poll(false) // still stale: nothing new
	if n := count(); n != 1 {
		t.Fatalf("stale flip published %d", n)
	}
	f.fail = nil
	f.advance(61 * time.Second)
	f.poll(false) // flips back
	if n := count(); n != 1 {
		t.Fatalf("recovery published %d", n)
	}
}

func TestTickPollsWatchedAndSurvivesPanics(t *testing.T) {
	f := newFx(t)
	var hotRepos = map[string]bool{"o/hot": true}
	panics := 0
	f.p = New(f.c, nil, Options{Now: f.clock,
		Watched: func() []string { return []string{"o/hot", "o/cold", "local/x", "bad slug", "O/HOT"} },
		Hot:     func(r string) bool { return hotRepos[r] },
		Tick: func(context.Context) {
			if panics++; panics == 1 {
				panic("tick boom")
			}
		}})
	f.p.safeTick(context.Background()) // panics inside Tick: swallowed, nothing polled
	if f.probes != 0 {
		t.Fatal("polled in a panicking tick")
	}
	f.p.safeTick(context.Background())
	if f.probes != 2 { // o/hot and o/cold (first poll is always due); local/x, bad slug and the duplicate are skipped
		t.Fatalf("probes %d", f.probes)
	}
	f.advance(61 * time.Second)
	f.p.safeTick(context.Background())
	if f.probes != 3 { // only the hot one is due again
		t.Fatalf("probes %d", f.probes)
	}
	// viewing makes a cold repo hot for 120 s
	f.p.MarkViewed("o/cold")
	f.advance(10 * time.Second)
	if !f.p.hot("o/cold") {
		t.Fatal("viewed repo is not hot")
	}
	f.advance(2 * time.Minute)
	if f.p.hot("o/cold") {
		t.Fatal("view window did not expire")
	}
	f.p.MarkViewed("*")
	if !f.p.hot("o/cold") {
		t.Fatal("* marks all hot")
	}
}

func TestStartRunsInitialTick(t *testing.T) {
	f := newFx(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	f.p.Start(ctx)
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if f.p.Snapshot("o/r").FetchedAt != nil {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("Start did not poll")
}

func TestMergeGate(t *testing.T) {
	ok := OpenPR{CI: "success", Approved: true}
	cases := []struct {
		name string
		pr   OpenPR
		solo bool
		want string
	}{
		{"ready", ok, false, ""},
		{"draft first", OpenPR{Draft: true, Conflict: true}, false, "PR is a draft"},
		{"conflict", OpenPR{Conflict: true, ChangesRequested: true}, false, "PR has a merge conflict"},
		{"changes", OpenPR{ChangesRequested: true, ThreadsOpen: 2}, true, "changes requested"},
		{"threads", OpenPR{ThreadsOpen: 1, Approved: true}, false, "unresolved review threads"},
		{"no approval", OpenPR{}, false, "no approving review"},
		{"solo skips approval", OpenPR{}, true, ""},
	}
	for _, tc := range cases {
		if got := MergeBlockers(tc.pr, tc.solo); got != tc.want {
			t.Errorf("%s: %q", tc.name, got)
		}
	}
	done, running := &GrindFact{State: "done"}, &GrindFact{State: "running"}
	ready := func(pr *OpenPR, g *GrindFact, on, solo bool) bool { return MergeReady(pr, g, on, solo) }
	if !ready(&ok, nil, false, false) || ready(nil, nil, false, false) || ready(&OpenPR{Approved: true, CI: "pending"}, nil, false, false) ||
		ready(&ok, nil, true, false) || ready(&ok, running, true, false) || !ready(&ok, done, true, false) || !ready(&ok, running, false, false) {
		t.Fatal("MergeReady table")
	}
}

func TestRefreshRoute(t *testing.T) {
	f := newFx(t)
	routes := Routes(Deps{Poller: f.p, ProductRepos: func(p string) ([]string, bool) {
		if p == "o/docs" {
			return []string{"o/r", "o/unwatched"}, true
		}
		return nil, false
	}})
	mux := http.NewServeMux()
	for _, r := range routes {
		mux.Handle(r.Pattern, r.Handler)
	}
	do := func(body string) int {
		req := httptest.NewRequest("POST", "/api/refresh", strings.NewReader(body))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, req)
		return rec.Code
	}
	wait := func(want int) {
		t.Helper()
		deadline := time.Now().Add(5 * time.Second)
		for time.Now().Before(deadline) {
			f.mu.Lock()
			n := f.fulls
			f.mu.Unlock()
			if n >= want {
				return
			}
			time.Sleep(5 * time.Millisecond)
		}
		t.Fatalf("expected %d full polls", want)
	}
	if code := do(`{}`); code != 202 {
		t.Fatalf("all: %d", code)
	}
	wait(1)
	if code := do(`{"repo":"O/R"}`); code != 202 {
		t.Fatalf("repo: %d", code)
	}
	wait(2)
	if code := do(`{"product":"o/docs"}`); code != 202 {
		t.Fatalf("product: %d", code)
	}
	wait(3)
	if do(`{"repo":"o/nope"}`) != 400 || do(`{"product":"nope"}`) != 400 {
		t.Fatal("unknown repo/product must be 400")
	}
}

func TestSeedAndFireFresh(t *testing.T) {
	p := New(ghtest.New(), nil, Options{Now: func() time.Time { return t0 }})
	fired := 0
	p.OnFresh(func(repo string, s Snapshot, prev Data) {
		fired++
		if repo != "o/r" || len(s.Data.Issues) != 1 || !prev.Empty() {
			t.Errorf("%v %v", s, prev)
		}
	})
	d := EmptyData()
	d.Issues = []Issue{{N: 1}}
	at := t0
	p.Seed(Snapshot{Repo: "o/r", Data: d, FetchedAt: &at})
	p.FireFresh("o/r", EmptyData())
	if s := p.Snapshot("O/R"); !s.Fresh() || fired != 1 {
		t.Fatalf("%v fired=%d", s, fired)
	}
}
